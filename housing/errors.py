from typing import Any


class HousingError(Exception):
    def __init__(self, code: str, message: str, details: list[dict[str, Any]] | None = None,
                 status: int = 422):
        super().__init__(message)
        self.code, self.message = code, message
        self.details, self.status = details or [], status

    def as_dict(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def issue(code, field, message, index=None):
    return {"code": code, "index": index, "field": field, "message": message}


def invalid(field, message, index=None):
    return HousingError("FIELD_VALIDATION_ERROR", "欄位驗證失敗。",
                        [issue("INVALID_VALUE", field, message, index)])
