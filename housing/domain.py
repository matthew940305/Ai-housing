"""不依賴 HTTP 或 SQLite 的欄位與月租規則。"""
import copy
import math
import re
from decimal import Decimal
from urllib.parse import urlsplit

from .errors import issue, invalid

FIELDS = tuple("租金 押金 付款方式 管理費 水費 電費 房型 坪數 樓層 地址 最短租期 可否開伙 可否養寵物 性別限制 設備 其他 來源網址 離中興距離".split())
UNKNOWN = "未揭露"
MAX_RAW_TEXT = 20_000
MAX_FIELD_TEXT = 20_000
# 超過此值不適合本專題；也避免 SQLite/JS 浮點溢位。
MAX_RENT = 1_000_000_000
NUMBER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
RENT_PATTERNS = [re.compile(p) for p in (
    rf"({NUMBER})", rf"({NUMBER})\s*元\s*/\s*月", rf"月租\s*({NUMBER})\s*元?",
)]


def finite(value):
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def rent_number(value, field="rent_monthly"):
    if type(value) not in (int, float) or not finite(value) or not 0 <= value <= MAX_RENT:
        raise invalid(field, f"必須是 0 到 {MAX_RENT} 的有限數值，不接受布林值。")
    return value


def parse_rent(value):
    """純數字（含數字字串）明確約定視為月租；只使用 fullmatch。"""
    if type(value) in (int, float):
        return rent_number(value, "租金")
    if not isinstance(value, str):
        return None
    if re.match(r"^(?:月租\s*)?[-−]\s*[0-9]", value.strip()) or value.strip().lower() in {"nan", "infinity", "+infinity", "-infinity", "inf", "-inf"}:
        raise invalid("租金", "租金不可為負值、NaN 或 Infinity。")
    for pattern in RENT_PATTERNS:
        match = pattern.fullmatch(value.strip())
        if match:
            number = float(match[1].replace(",", ""))
            return rent_number(number, "租金")
    return None


def valid_source(value):
    try:
        parts = urlsplit(value)
        return parts.scheme in ("http", "https") and bool(parts.hostname) and not any(c.isspace() for c in value)
    except ValueError:
        return False


def normalize_fields(original, index=None):
    fields, errors, warnings = {}, [], []
    for name in FIELDS:
        value = original.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            value = UNKNOWN
            warnings.append(issue("MISSING_FIELD", name, "缺少、null 或空白，已補為未揭露。", index))
        if name == "設備":
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list) or not all(isinstance(v, str) and len(v) <= MAX_FIELD_TEXT for v in value):
                errors.append(issue("INVALID_TYPE", name, "設備必須是文字或字串陣列。", index))
                continue
        elif type(value) in (int, float):
            if not finite(value) or (name == "租金" and not 0 <= value <= MAX_RENT):
                errors.append(issue("INVALID_NUMBER", name, "數值必須有限；租金不可負值或超過上限。", index))
                continue
            value = format(Decimal(str(value)), "f")
        elif not isinstance(value, str):
            errors.append(issue("INVALID_TYPE", name, "必須是文字或有限數字，不接受布林、物件或陣列。", index))
            continue
        if isinstance(value, str) and len(value) > MAX_FIELD_TEXT:
            errors.append(issue("TOO_LONG", name, f"最多 {MAX_FIELD_TEXT} 字元。", index))
            continue
        fields[name] = copy.deepcopy(value)
    return fields, errors, warnings


def current_warnings(fields, raw_text, rent, source, index=None):
    warnings = []
    for name, value in fields.items():
        values = value if isinstance(value, list) else [value]
        if not values or all(v.strip() == UNKNOWN for v in values):
            warnings.append(issue("UNDISCLOSED", name, "此欄尚未揭露，請對照原文。", index))
        if any("待確認" in v for v in values):
            warnings.append(issue("NEEDS_CONFIRMATION", name, "保留待確認內容，請人工核對。", index))
    if not raw_text.strip():
        warnings.append(issue("MISSING_RAW_TEXT", "raw_text", "缺少原始刊登文字，無法核對 AI 擷取內容。", index))
    if rent is None:
        warnings.append(issue("UNKNOWN_RENT", "租金", "月租尚未確定；價格篩選預設排除。", index))
    if source == "manual":
        warnings.append(issue("MANUAL_RENT", "rent_monthly", "月租由人工指定或清除；請核對租金文字。", index))
    url = fields["來源網址"]
    if url != UNKNOWN and not valid_source(url):
        warnings.append(issue("INVALID_SOURCE_URL", "來源網址", "不是明確的 HTTP(S) 網址；僅保留文字，不應直接作為連結。", index))
    return warnings
