"""python -m scripts.demo [--base-url http://127.0.0.1:8000]"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from housing.service import HousingService

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="以明確標示的虛構資料跑通預覽、匯入、讀取、修改、再讀取、匯出。")
    parser.add_argument("--base-url", help="指定後透過真正的 HTTP 連線；預設使用獨立暫存資料庫直接呼叫 Python。")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    req = {"json_text": (ROOT / "examples/demo_blue.json").read_text(encoding="utf-8"),
           "metadata": json.loads((ROOT / "examples/demo_metadata.json").read_text(encoding="utf-8"))}
    with tempfile.TemporaryDirectory(prefix="housing-demo-") as directory:
        if args.base_url:
            import httpx
            client = httpx.Client(base_url=args.base_url.rstrip("/"), timeout=10, trust_env=False)

            def call(method, path, data=None):
                response = client.request(method, path, **({"json": data} if data is not None else {}))
                response.raise_for_status()
                return response.json()

            preview = lambda data: call("POST", "/imports/preview", data)
            commit = lambda data: call("POST", "/imports/commit", data)
            get = lambda key: call("GET", f"/properties/{key}")
            update = lambda key, patch: call("PATCH", f"/properties/{key}", patch)
            export = lambda: call("GET", "/properties/export")
        else:
            service = HousingService(Path(directory) / "demo.sqlite3")
            preview, commit = service.preview, service.commit
            get, update, export = service.get_property, service.update_property, service.export_properties
            client = None
        try:
            result = preview(req)
            assert result["can_commit"]
            print(f"1 預覽：{result['count']} 筆，可以匯入；尚未寫入")
            req["edits"] = [{"fields": {"租金": "月租8300元"}, "rent_monthly": 8300}, None]
            assert preview(req)["items"][0]["property"]["rent_monthly"] == 8300
            print("1b 使用者修改草稿月租為8300，再預覽；仍未儲存，原始 AI 月租8000保留")
            req["edits"][0]["reviewed"] = True
            result = commit({**req, "request_id": "demo-" + str(uuid4())})
            prop = result["properties"][0]
            print(f"2 匯入：{result['count']} 筆，第一筆 id={prop['id']}")
            before = get(prop["id"])
            assert before["rent_monthly"] == 8300 and before["reviewed"] is True
            assert before["original_ai_fields"]["租金"] == "8,000元/月"
            print(f"3 讀取：月租={before['rent_monthly']}，reviewed={before['reviewed']}")
            update(prop["id"], {"fields": {"租金": "月租8500元"}, "rent_monthly": 8500})
            after = get(prop["id"])
            assert after["rent_monthly"] == 8500 and after["original_ai_fields"] == before["original_ai_fields"]
            print(f"4 修改後再讀取：月租={after['rent_monthly']}，原始 AI 值保留，reviewed={after['reviewed']}")
            assert update(prop["id"], {"reviewed": True})["reviewed"] is True
            print("5 使用者明確確認：reviewed=true")
            snapshot = export()
            assert any(p["id"] == prop["id"] for p in snapshot["properties"])
            print(f"6 匯出：schema_version={snapshot['schema_version']}，{snapshot['count']} 筆。完整流程 PASS")
        finally:
            if client:
                client.close()


if __name__ == "__main__":
    main()
