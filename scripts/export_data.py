"""讀取設定的 SQLite 資料庫，匯出給前端隊友。"""
import argparse
import json
import sys
from pathlib import Path

from housing.errors import HousingError
from housing.service import HousingService


def main():
    parser = argparse.ArgumentParser(description="匯出目前房源快照（包含原始 AI 值與人工修改）。")
    parser.add_argument("--output", default="exports/housing-export.json")
    parser.add_argument("--db-path", help="省略時使用 HOUSING_DB_PATH 或 data/housing.sqlite3")
    parser.add_argument("--reviewed-only", action="store_true")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        snapshot = HousingService(args.db_path).export_properties(reviewed_only=args.reviewed_only)
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(snapshot, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        print(f"匯出 {snapshot['count']} 筆：{output}")
    except HousingError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
