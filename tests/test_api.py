import json

import pytest
from fastapi.testclient import TestClient

from housing.api import MAX_BODY_BYTES, create_app
from test_imports import payload


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite3", ["http://localhost:5173", "http://localhost:8080"])) as client:
        yield client


def test_full_http_flow(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/properties").json() == {"count": 0, "properties": []}
    req = payload([{"租金": 8000, "設備": ["冷氣"]}, {"租金": "5700～7700"}],
                  metadata=[{"raw_text": "虛構房源 A 月租8000元"}, {"raw_text": "虛構房源 B 租金5700～7700"}])
    preview = client.post("/imports/preview", json=req)
    assert preview.status_code == 200 and preview.json()["can_commit"]
    assert client.get("/properties").json()["count"] == 0
    commit = client.post("/imports/commit", json={**req, "request_id": "http-flow"})
    assert commit.status_code == 200
    prop = commit.json()["properties"][0]
    key = prop["id"]
    assert client.get(f"/properties/{key}").json() == prop
    assert client.patch(f"/properties/{key}", json={"reviewed": True}).json()["reviewed"] is True
    updated = client.patch(f"/properties/{key}", json={"fields": {"租金": "月租8500元"}, "rent_monthly": 8500}).json()
    assert updated["reviewed"] is False
    assert updated["original_ai_fields"] == prop["original_ai_fields"]
    assert client.get(f"/properties/{key}").json() == updated
    assert client.get("/properties?min_rent=8000&max_rent=9000").json()["count"] == 1
    assert client.get("/properties?min_rent=8000&max_rent=9000&include_unknown=true").json()["count"] == 2
    assert client.get("/properties?sort=rent_desc").json()["properties"][-1]["rent_monthly"] is None
    assert client.post("/imports/commit", json={**req, "request_id": "http-flow"}).json()["replayed"] is True
    assert client.get("/properties").json()["count"] == 2


@pytest.mark.parametrize("method,path,body,code,status", [
    ("post", "/imports/preview", {"json_text": "bad"}, "JSON_SYNTAX_ERROR", 400),
    ("post", "/imports/preview", payload({"no": []}), "UNSUPPORTED_STRUCTURE", 422),
    ("post", "/imports/commit", payload([{"租金": 8000}, {"租金": True}], request_id="fail"), "FIELD_VALIDATION_ERROR", 422),
    ("get", "/properties/missing", None, "PROPERTY_NOT_FOUND", 404),
    ("patch", "/properties/missing", {"reviewed": True}, "PROPERTY_NOT_FOUND", 404),
    ("get", "/properties?min_rent=NaN", None, "FIELD_VALIDATION_ERROR", 422),
    ("get", "/properties?max_rent=Infinity", None, "FIELD_VALIDATION_ERROR", 422),
    ("get", "/properties?reviewed=1", None, "FIELD_VALIDATION_ERROR", 422),
    ("get", "/properties?min_rent=abc", None, "FIELD_VALIDATION_ERROR", 422),
])
def test_error_envelope(client, method, path, body, code, status):
    response = client.request(method, path, **({"json": body} if body is not None else {}))
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert isinstance(response.json()["error"]["details"], list)
    assert client.get("/properties").json()["count"] == 0


def test_http_database_error_envelope(client):
    service = client.app.state.service
    with service.store.connection(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_all BEFORE INSERT ON properties BEGIN SELECT RAISE(ABORT, 'test'); END")
    response = client.post("/imports/commit", json=payload({"租金": 8000}, request_id="db-fail"))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "DATABASE_ERROR"


def test_http_outer_syntax_and_size_limit(client):
    response = client.post("/imports/preview", content="{oops", headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "JSON_SYNTAX_ERROR"
    response = client.post("/imports/preview", content=b" " * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FIELD_VALIDATION_ERROR"


def test_cors_is_configurable(client):
    for origin in ("http://localhost:5173", "http://localhost:8080"):
        response = client.options("/imports/preview", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        assert response.headers["access-control-allow-origin"] == origin
    response = client.options("/imports/preview", headers={"Origin": "http://localhost:9999", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in response.headers


def test_export_full_and_reviewed_only(client):
    result = client.post("/imports/commit", json=payload([{"租金": 8000}, {"租金": "未揭露"}], request_id="export")).json()
    key = result["properties"][0]["id"]
    client.patch(f"/properties/{key}", json={"fields": {"房型": "人工修正套房"}})
    client.patch(f"/properties/{key}", json={"reviewed": True})
    response = client.get("/properties/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    snapshot = response.json()
    assert snapshot["schema_version"] == "1.0" and snapshot["count"] == 2
    assert snapshot["properties"][0]["fields"]["房型"] == "人工修正套房"
    assert snapshot["properties"][0]["original_ai_fields"] == {"租金": 8000}
    assert snapshot["properties"][1]["rent_monthly"] is None
    assert client.get("/properties/export?reviewed_only=true").json()["count"] == 1
    assert client.get("/properties/export?reviewed_only=no").status_code == 422


def test_http_edit_before_commit_then_read_for_comparison(client):
    original = [{"租金": "待確認：8000或8500", "房型": "待確認：套房或雅房"}]
    request = payload(original, metadata=[{"raw_text": "虛構全文：8000或8500，套房或雅房待核對。"}],
                      edits=[{"fields": {"租金": "月租8500元", "房型": "套房"}}])
    preview = client.post("/imports/preview", json=request).json()
    assert preview["can_commit"]
    assert preview["items"][0]["property"]["rent_monthly"] == 8500
    assert client.get("/properties").json()["count"] == 0
    request["edits"][0]["reviewed"] = True
    result = client.post("/imports/commit", json={**request, "request_id": "http-draft"})
    assert result.status_code == 200
    saved = result.json()["properties"][0]
    assert saved["reviewed"] is True
    assert saved["original_ai_fields"] == original[0]
    comparison = client.get("/properties?reviewed=true&max_rent=9000").json()
    assert comparison["count"] == 1
    assert comparison["properties"][0]["fields"]["房型"] == "套房"
