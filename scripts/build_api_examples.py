"""以真實 ASGI 路由產生交接文件完整範例，避免手寫回應與程式脫節。"""
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from housing.api import create_app

ROOT = Path(__file__).resolve().parents[1]
MARKER = "<!-- GENERATED_API_EXAMPLES -->"


def pretty(data):
    return json.dumps(data, ensure_ascii=False, indent=2)


def main():
    sections = [MARKER, "## 完整 HTTP 請求與回應範例\n"]
    with tempfile.TemporaryDirectory(prefix="housing-docs-") as folder:
        with TestClient(create_app(Path(folder) / "docs.sqlite3")) as client:
            records = json.loads((ROOT / "examples/demo_blue.json").read_text(encoding="utf-8"))[:1]
            metadata = json.loads((ROOT / "examples/demo_metadata.json").read_text(encoding="utf-8"))[:1]
            request = {"json_text": json.dumps(records, ensure_ascii=False), "metadata": metadata}

            def capture(method, path, body=None, label=None):
                response = client.request(method, path, **({"json": body} if body is not None else {}))
                response.raise_for_status()
                sections.append(f"### {label or (method + ' ' + path)}\n\n```http\n{method} {path} HTTP/1.1\nHost: 127.0.0.1:8000" +
                                ("\nContent-Type: application/json" if body is not None else "") + "\n```\n")
                if body is not None:
                    sections.append("請求 body：\n\n```json\n" + pretty(body) + "\n```\n")
                sections.append(f"回應 HTTP {response.status_code}：\n\n```json\n{pretty(response.json())}\n```\n")
                return response.json()

            capture("GET", "/health")
            capture("POST", "/imports/preview", request)
            request["edits"] = [{"fields": {"租金": "月租8300元"}, "rent_monthly": 8300}]
            capture("POST", "/imports/preview", request, "POST /imports/preview 使用者修改後再預覽（未儲存）")
            request["edits"][0]["reviewed"] = True
            result = capture("POST", "/imports/commit", {**request, "request_id": "frontend-doc-example"})
            key = result["properties"][0]["id"]
            capture("GET", "/properties?min_rent=6000&max_rent=9000&include_unknown=true&reviewed=true&sort=rent_asc")
            capture("GET", f"/properties/{key}")
            capture("PATCH", f"/properties/{key}", {"fields": {"房型": "人工確認獨立套房"}}, "PATCH 保存人工修改")
            capture("PATCH", f"/properties/{key}", {"reviewed": True}, "PATCH 獨立明確確認")
            capture("GET", "/properties/export?reviewed_only=true")
    path = ROOT / "FRONTEND_HANDOFF.md"
    prefix = path.read_text(encoding="utf-8").split(MARKER)[0].rstrip()
    path.write_text(prefix + "\n\n" + "\n".join(sections).rstrip() + "\n", encoding="utf-8")
    print(f"已產生 {path.name} 完整 API 範例")


if __name__ == "__main__":
    main()
