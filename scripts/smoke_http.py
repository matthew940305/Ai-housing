"""啟動真正 Uvicorn，走 TCP HTTP 完整示範並驗證 JSON 檔案匯出。"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="housing-http-") as folder:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = {**os.environ, "HOUSING_DB_PATH": str(Path(folder) / "http.sqlite3")}
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        log_path = Path(folder) / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "housing.api:app", "--host", "127.0.0.1",
                                        "--port", str(port), "--log-level", "warning"],
                                       cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=flags)
            try:
                base = f"http://127.0.0.1:{port}"
                with httpx.Client(base_url=base, timeout=2, trust_env=False) as client:
                    for attempt in range(100):
                        if process.poll() is not None:
                            raise RuntimeError("Uvicorn 提前結束：" + log_path.read_text(encoding="utf-8"))
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Uvicorn 未於期限內就緒。")
                    assert client.get("/properties").json()["count"] == 0
                    subprocess.run([sys.executable, "-m", "scripts.demo", "--base-url", base],
                                   cwd=ROOT, env=env, check=True, timeout=30, creationflags=flags)
                    snapshot = client.get("/properties/export").json()
                    assert snapshot["count"] == 2
                    assert [p["rent_monthly"] for p in snapshot["properties"]] == [8500, None]
                    assert snapshot["properties"][0]["reviewed"] is True
                    # 可直接交給前端試讀的完全虛構快照。
                    (ROOT / "examples/demo_export.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                output = Path(folder) / "export.json"
                subprocess.run([sys.executable, "-m", "scripts.export_data", "--output", str(output)],
                               cwd=ROOT, env=env, check=True, timeout=10, creationflags=flags)
                disk = json.loads(output.read_text(encoding="utf-8"))
                assert disk["properties"] == snapshot["properties"]
                print("真實 TCP HTTP、資料庫重連、API 匯出與命令列匯出 PASS")
            finally:
                if os.name == "nt" and process.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags, check=False)
                elif process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
