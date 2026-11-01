"""Python 前端及 HTTP 共用的業務邏輯入口。"""
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from .adapter import normalize_import
from .domain import FIELDS, MAX_RAW_TEXT, current_warnings, normalize_fields, parse_rent, rent_number, valid_source
from .errors import HousingError, invalid, issue
from .storage import SQLiteStore, dumps


def now():
    return datetime.now(timezone.utc).isoformat()


def annotate_duplicates(targets, all_properties):
    """疑似重複只作即時計算提示，不合併，也不影響 reviewed。"""
    for prop in targets:
        prop["warnings"] = [w for w in prop["warnings"] if w["code"] != "POSSIBLE_DUPLICATE"]
        url = prop["fields"].get("來源網址", "")
        if valid_source(url) and any(other is not prop and other.get("id") != prop.get("id", object())
                                     and other["fields"].get("來源網址") == url for other in all_properties):
            prop["warnings"].append(issue("POSSIBLE_DUPLICATE", "來源網址", "其他房源使用相同來源網址；可能是不同房型，未合併或覆寫。"))
    return targets


class HousingService:
    def __init__(self, db_path=None):
        self.store = SQLiteStore(db_path or os.getenv("HOUSING_DB_PATH", "data/housing.sqlite3"))

    def health(self):
        with self.store.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    def preview(self, payload):
        result = normalize_import(payload)
        with self.store.connection() as conn:
            existing = self.store.all(conn)
        incoming = [i["property"] for i in result["items"] if not i["errors"]]
        annotate_duplicates(incoming, existing + incoming)
        for item in result["items"]:
            if item["property"]:
                item["warnings"] = item["property"]["warnings"]
        return result

    def commit(self, payload):
        result = normalize_import(payload, commit=True)
        if not result["can_commit"]:
            raise HousingError("FIELD_VALIDATION_ERROR", "整批匯入取消，請先修正所有阻擋錯誤。",
                               [e for item in result["items"] for e in item["errors"]])
        # 以解析後原始欄位、metadata 及人工 edits 作 hash；忽略 JSON 排版差異。
        identity = {"records": [i["property"]["original_ai_fields"] for i in result["items"]],
                    "metadata": [i["property"]["source_metadata"] for i in result["items"]],
                    "wrapper": result["wrapper_metadata"]}
        if payload.get("edits") and any(payload["edits"]):
            identity["edits"] = payload["edits"]
        fingerprint = hashlib.sha256(dumps(identity).encode("utf-8")).hexdigest()
        with self.store.connection(write=True) as conn:
            previous = conn.execute("SELECT * FROM import_requests WHERE request_id = ?", (payload["request_id"],)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise HousingError("IMPORT_REQUEST_CONFLICT", "此 request_id 已用於不同內容，請為新匯入產生新識別碼。", status=409)
                props = [self.store.get(conn, key) for key in json.loads(previous["property_ids"])]
                replayed = True
            else:
                props = []
                for item in result["items"]:
                    prop = copy.deepcopy(item["property"])
                    stamp = now()
                    prop.update(id=str(uuid4()), created_at=stamp, updated_at=stamp)
                    self.store.insert(conn, prop)
                    props.append(prop)
                conn.execute("INSERT INTO import_requests VALUES (?, ?, ?, ?)",
                             (payload["request_id"], fingerprint, dumps([p["id"] for p in props]), dumps(result["wrapper_metadata"])))
                replayed = False
            annotate_duplicates(props, self.store.all(conn))
        return {"request_id": payload["request_id"], "replayed": replayed, "count": len(props),
                "properties": props, "wrapper_metadata": result["wrapper_metadata"]}

    def create(self, ai_fields, *, raw_text="", source_url=None, request_id):
        """單筆新增亦走同一個適配器、驗證與交易。"""
        try:
            json_text = dumps(ai_fields)
        except (TypeError, ValueError, OverflowError) as exc:
            raise invalid(None, "新增資料必須可序列化為 JSON，數值不可為 NaN 或 Infinity。") from exc
        return self.commit({"request_id": request_id, "json_text": json_text,
                            "metadata": [{"raw_text": raw_text, "source_url": source_url}]})["properties"][0]

    def list_properties(self, *, min_rent=None, max_rent=None, include_unknown=False, reviewed=None, sort="rent_asc"):
        if min_rent is not None:
            rent_number(min_rent, "min_rent")
        if max_rent is not None:
            rent_number(max_rent, "max_rent")
        if min_rent is not None and max_rent is not None and min_rent > max_rent:
            raise invalid("min_rent", "最低月租不可高於最高月租。")
        if type(include_unknown) is not bool or (reviewed is not None and type(reviewed) is not bool):
            raise invalid("reviewed/include_unknown", "需要布林值。")
        if sort not in ("rent_asc", "rent_desc"):
            raise invalid("sort", "只允許 rent_asc 或 rent_desc。")
        with self.store.connection() as conn:
            all_props = self.store.all(conn)
        annotate_duplicates(all_props, all_props)
        result = []
        for prop in all_props:
            rent = prop["rent_monthly"]
            if reviewed is not None and prop["reviewed"] != reviewed:
                continue
            if rent is None:
                if (min_rent is not None or max_rent is not None) and not include_unknown:
                    continue
            elif (min_rent is not None and rent < min_rent) or (max_rent is not None and rent > max_rent):
                continue
            result.append(prop)
        return sorted(result, key=lambda p: (p["rent_monthly"] is None,
                                             (p["rent_monthly"] or 0) * (1 if sort == "rent_asc" else -1),
                                             p["created_at"], p["id"]))

    def get_property(self, property_id):
        with self.store.connection() as conn:
            prop = self.store.get(conn, property_id)
            return annotate_duplicates([prop], self.store.all(conn))[0]

    def export_properties(self, *, reviewed_only=False):
        if type(reviewed_only) is not bool:
            raise invalid("reviewed_only", "需要布林值。")
        properties = self.list_properties(reviewed=True if reviewed_only else None)
        return {"schema_version": "1.0", "exported_at": now(), "count": len(properties), "properties": properties}

    def update_property(self, property_id, patch):
        if not isinstance(patch, dict) or not patch:
            raise invalid(None, "PATCH 需要非空物件。")
        if set(patch) - {"fields", "raw_text", "rent_monthly", "reviewed"}:
            raise invalid(None, "只允許 fields、raw_text、rent_monthly、reviewed；系統欄位不可修改。")
        if "reviewed" in patch and type(patch["reviewed"]) is not bool:
            raise invalid("reviewed", "需要 true 或 false。")
        with self.store.connection(write=True) as conn:
            prop = self.store.get(conn, property_id)
            before = copy.deepcopy(prop)
            if "fields" in patch:
                edits = patch["fields"]
                if not isinstance(edits, dict) or set(edits) - set(FIELDS):
                    raise invalid("fields", "只允許契約中的 18 個中文欄位。")
                fields, errors, _ = normalize_fields({**prop["fields"], **edits})
                if errors:
                    raise HousingError("FIELD_VALIDATION_ERROR", "欄位驗證失敗。", errors)
                prop["fields"] = fields
            if "raw_text" in patch:
                text = patch["raw_text"]
                if not isinstance(text, str) or len(text) > MAX_RAW_TEXT:
                    raise invalid("raw_text", f"需要至多 {MAX_RAW_TEXT} 字元的文字。")
                prop["raw_text"] = text
            # 即使有人工覆寫，租金欄位的明確非法數字仍須拒絕。
            parsed = parse_rent(prop["fields"]["租金"])
            if "rent_monthly" in patch:
                prop["rent_monthly"] = None if patch["rent_monthly"] is None else rent_number(patch["rent_monthly"])
                prop["rent_monthly_source"] = "manual"
            elif prop["rent_monthly_source"] != "manual":
                prop["rent_monthly"] = parsed
                prop["rent_monthly_source"] = "safe_parse" if parsed is not None else "unknown"
            changed = any(prop[k] != before[k] for k in ("fields", "raw_text", "rent_monthly", "rent_monthly_source"))
            if changed and patch.get("reviewed") is True:
                raise invalid("reviewed", "先保存修改（reviewed 將為 false），再獨立送出 reviewed: true 明確確認。")
            prop["reviewed"] = False if changed else patch.get("reviewed", prop["reviewed"])
            if prop != before:
                prop["updated_at"] = now()
                prop["warnings"] = current_warnings(prop["fields"], prop["raw_text"], prop["rent_monthly"], prop["rent_monthly_source"])
                self.store.update(conn, prop)
            annotate_duplicates([prop], self.store.all(conn))
            return prop
