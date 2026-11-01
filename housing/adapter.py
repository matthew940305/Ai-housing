"""Blue JSON 的唯一匯入適配器。只解包明確允許的鍵。"""
import copy
import json
import math
import re

from .domain import FIELDS, MAX_RAW_TEXT, current_warnings, normalize_fields, parse_rent, rent_number, valid_source
from .errors import HousingError, invalid, issue

MAX_JSON_CHARS = 1_048_576
MAX_BATCH = 100
WRAPPER_KEYS = ("properties", "data", "results")
FENCE = re.compile(r"\A```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```\Z", re.IGNORECASE)


def _strict_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"JSON 內有重複的鍵：{key}")
        obj[key] = value
    return obj


def _finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON 數值必須有限，不能包含 NaN、Infinity 或溢位數字。")
    if isinstance(value, dict):
        for v in value.values():
            _finite_tree(v)
    elif isinstance(value, list):
        for v in value:
            _finite_tree(v)


def _property(obj):
    return isinstance(obj, dict) and bool(set(obj).intersection(FIELDS))


def _candidate(obj):
    return _property(obj) or (isinstance(obj, list) and bool(obj) and all(_property(x) for x in obj))


def extract_records(json_text):
    if not isinstance(json_text, str) or not 1 <= len(json_text) <= MAX_JSON_CHARS:
        raise invalid("json_text", f"需要 1 到 {MAX_JSON_CHARS} 字元的 JSON 文字。")
    text = json_text.strip()
    match = FENCE.fullmatch(text)
    if match:
        text = match[1]
    try:
        data = json.loads(text, object_pairs_hook=_strict_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"不合法的 JSON 常數：{x}")))
        _finite_tree(data)
    except json.JSONDecodeError as exc:
        raise HousingError("JSON_SYNTAX_ERROR", f"JSON 語法錯誤：第 {exc.lineno} 行、第 {exc.colno} 欄。",
                           [issue("INVALID_JSON", "json_text", exc.msg)], 400) from exc
    except (ValueError, RecursionError) as exc:
        raise HousingError("JSON_SYNTAX_ERROR", f"JSON 無法讀取：{exc}", status=400) from exc
    wrapper_metadata = {}
    if isinstance(data, dict):
        # 不只檢查允許鍵；若存在另一個房源陣列，也必須回報歧義。
        if not _property(data):
            candidates = [k for k, v in data.items() if _candidate(v)]
            if len(candidates) > 1:
                raise HousingError("UNSUPPORTED_STRUCTURE", "有多個可能的房源集合，請明確提供單一陣列。",
                                   [issue("AMBIGUOUS_WRAPPER", None, ", ".join(candidates))])
            if len(candidates) != 1 or candidates[0] not in WRAPPER_KEYS:
                raise HousingError("UNSUPPORTED_STRUCTURE", "需要房源物件、陣列，或 properties/data/results 包裝。")
            key = candidates[0]
            wrapper_metadata = copy.deepcopy({k: v for k, v in data.items() if k != key})
            data = data[key]
    if isinstance(data, dict) and _property(data):
        data = [data]
    if not isinstance(data, list) or not data:
        raise HousingError("UNSUPPORTED_STRUCTURE", "房源必須是非空物件或非空陣列。")
    if len(data) > MAX_BATCH:
        raise invalid("json_text", f"一批最多 {MAX_BATCH} 筆。")
    return data, wrapper_metadata


def normalize_import(payload, *, commit=False):
    if not isinstance(payload, dict):
        raise invalid(None, "請求必須是 JSON 物件。")
    allowed = {"json_text", "metadata", "edits"} | ({"request_id"} if commit else set())
    if set(payload) - allowed:
        raise invalid(None, f"不支援的請求欄位：{sorted(set(payload) - allowed)}")
    if commit:
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id):
            raise invalid("request_id", "需要 1–100 字元的英數、底線或連字號識別碼。")
    records, wrapper = extract_records(payload.get("json_text"))
    metadata = payload.get("metadata")
    if metadata is None:
        metadata = [{} for _ in records]
    if not isinstance(metadata, list) or len(metadata) != len(records):
        raise invalid("metadata", "必須是與房源陣列等長、依相同索引逐筆對應的物件陣列。")
    edits = payload.get("edits")
    if edits is None:
        edits = [None for _ in records]
    if not isinstance(edits, list) or len(edits) != len(records):
        raise invalid("edits", "必須是與房源等長的修改陣列；未修改的列可填 null。")
    items = []
    for index, (original, meta, edit) in enumerate(zip(records, metadata, edits)):
        errors, warnings = [], []
        if not _property(original):
            items.append({"index": index, "property": None, "errors": [issue("INVALID_RECORD", None, "每筆至少需要一個契約欄位。", index)], "warnings": []})
            continue
        edit = {} if edit is None else edit
        if not isinstance(edit, dict) or set(edit) - {"fields", "rent_monthly", "reviewed"}:
            errors.append(issue("INVALID_EDIT", "edits", "只允許 fields、rent_monthly 與 reviewed；不能修改原始 AI 資料。", index))
            edit = {}
        field_edits = edit.get("fields", {})
        if not isinstance(field_edits, dict) or set(field_edits) - set(FIELDS):
            errors.append(issue("INVALID_EDIT", "fields", "只允許修改 18 個契約欄位。", index))
            field_edits = {}
        if "reviewed" in edit and type(edit["reviewed"]) is not bool:
            errors.append(issue("INVALID_TYPE", "reviewed", "需要明確的 true 或 false。", index))
        if not isinstance(meta, dict) or set(meta) - {"raw_text", "source_url"}:
            errors.append(issue("INVALID_METADATA", "metadata", "只允許 raw_text 與 source_url。", index))
            meta = {}
        raw_text = meta.get("raw_text", "")
        if not isinstance(raw_text, str) or len(raw_text) > MAX_RAW_TEXT:
            errors.append(issue("INVALID_RAW_TEXT", "raw_text", f"必須是至多 {MAX_RAW_TEXT} 字元的文字。", index))
            raw_text = ""
        source_url = meta.get("source_url")
        if source_url is not None and (not isinstance(source_url, str) or len(source_url) > 2048 or not valid_source(source_url)):
            errors.append(issue("INVALID_SOURCE_URL", "source_url", "必須是至多 2048 字元的 HTTP(S) 網址或 null。", index))
        # 使用者修正只影響目前 fields，original_ai_fields 始終使用未修改的 JSON。
        fields, field_errors, initial = normalize_fields({**original, **field_edits}, index)
        errors.extend(field_errors)
        warnings.extend(initial)
        if isinstance(source_url, str) and valid_source(source_url):
            if fields.get("來源網址") == "未揭露":
                fields["來源網址"] = source_url
            elif fields.get("來源網址") != source_url:
                warnings.append(issue("SOURCE_CONFLICT", "來源網址", "AI 網址與逐筆來源不同；兩者皆保留，請核對。", index))
        rent = None
        if "租金" in fields:
            try:
                rent = parse_rent(fields["租金"])
            except HousingError as exc:
                errors.extend({**d, "index": index} for d in exc.details)
        source = "safe_parse" if rent is not None else "unknown"
        if "rent_monthly" in edit:
            try:
                rent = None if edit["rent_monthly"] is None else rent_number(edit["rent_monthly"])
                source = "manual"
            except HousingError as exc:
                errors.extend({**d, "index": index} for d in exc.details)
        prop = {"fields": fields, "original_ai_fields": copy.deepcopy(original),
                "extra_fields": copy.deepcopy({k: v for k, v in original.items() if k not in FIELDS}),
                "raw_text": raw_text, "source_metadata": copy.deepcopy(meta),
                "reviewed": edit.get("reviewed") is True, "rent_monthly": rent, "rent_monthly_source": source,
                "import_warnings": copy.deepcopy(warnings)}
        if not errors:
            warnings += current_warnings(fields, raw_text, rent, source, index)
        prop["warnings"] = warnings
        items.append({"index": index, "property": prop, "errors": errors, "warnings": warnings})
    return {"can_commit": not any(i["errors"] for i in items), "count": len(items),
            "items": items, "wrapper_metadata": wrapper}
