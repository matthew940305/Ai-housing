"""薄 HTTP 層，全部規則交給 HousingService。"""
import json
import os

from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

from .errors import HousingError, invalid, issue
from .service import HousingService

MAX_BODY_BYTES = 2_097_152


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                error = HousingError("FIELD_VALIDATION_ERROR", f"HTTP 請求最多 {MAX_BODY_BYTES} bytes。", status=413)
                return await JSONResponse(error.as_dict(), status_code=error.status)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def limited_receive():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, limited_receive, send)


def query_bool(value, field, default=None):
    if value is None:
        return default
    if value not in ("true", "false"):
        raise invalid(field, "只接受 true 或 false。")
    return value == "true"


def query_number(value, field):
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise invalid(field, "需要數值。") from exc


def create_app(db_path=None, cors_origins=None):
    service = HousingService(db_path)
    app = FastAPI(title="中興 AI 租屋資訊助手", version="1.0.0",
                  description="接收 Blue JSON、預覽及儲存。詳細契約見 FRONTEND_HANDOFF.md。")
    app.state.service = service
    origins = cors_origins if cors_origins is not None else [x.strip() for x in os.getenv("HOUSING_CORS_ORIGINS", "").split(",") if x.strip()]
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type"])

    @app.exception_handler(HousingError)
    async def domain_error(request: Request, exc: HousingError):
        return JSONResponse(exc.as_dict(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def request_error(request: Request, exc: RequestValidationError):
        syntax = any(e["type"] == "json_invalid" for e in exc.errors())
        error = HousingError("JSON_SYNTAX_ERROR" if syntax else "FIELD_VALIDATION_ERROR", "HTTP JSON 語法錯誤。" if syntax else "HTTP 請求格式錯誤。",
                             [issue(e["type"], ".".join(map(str, e["loc"])), e["msg"]) for e in exc.errors()], 400 if syntax else 422)
        return JSONResponse(error.as_dict(), status_code=error.status)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(HousingError("HTTP_ERROR", str(exc.detail), status=exc.status_code).as_dict(), status_code=exc.status_code)

    @app.get("/health")
    def health():
        return service.health()

    @app.post("/imports/preview")
    def preview(payload=Body(...)):
        return service.preview(payload)

    @app.post("/imports/commit")
    def commit(payload=Body(...)):
        return service.commit(payload)

    @app.get("/properties")
    def properties(request: Request):
        q = request.query_params
        if set(q) - {"min_rent", "max_rent", "include_unknown", "reviewed", "sort"}:
            raise invalid(None, "不支援的篩選參數。")
        items = service.list_properties(min_rent=query_number(q.get("min_rent"), "min_rent"),
                                        max_rent=query_number(q.get("max_rent"), "max_rent"),
                                        include_unknown=query_bool(q.get("include_unknown"), "include_unknown", False),
                                        reviewed=query_bool(q.get("reviewed"), "reviewed"), sort=q.get("sort", "rent_asc"))
        return {"count": len(items), "properties": items}

    @app.get("/properties/export")
    def export_properties(reviewed_only: str | None = None):
        result = service.export_properties(reviewed_only=query_bool(reviewed_only, "reviewed_only", False))
        return Response(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2),
                        media_type="application/json", headers={"Content-Disposition": 'attachment; filename="housing-export.json"'})

    @app.get("/properties/{property_id}")
    def get_property(property_id: str):
        return service.get_property(property_id)

    @app.patch("/properties/{property_id}")
    def patch_property(property_id: str, payload=Body(...)):
        return service.update_property(property_id, payload)

    return app


app = create_app()
