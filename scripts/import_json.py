"""預覽 Blue JSON 檔；只有帶 --commit 與 request-id 才會寫入。"""
import argparse
import json
import sys
from pathlib import Path

from housing.errors import HousingError
from housing.service import HousingService


def main():
    parser = argparse.ArgumentParser(description="預覽／確認匯入 Blue JSON，所有規則使用共用 HousingService。")
    parser.add_argument("--json-file", required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--metadata-file", help="與房源等長的逐筆 raw_text/source_url 陣列 JSON 檔")
    source.add_argument("--raw-text-file", help="只有單筆房源時可直接提供對應原文檔；批次請用 metadata-file")
    parser.add_argument("--db-path")
    parser.add_argument("--edits-file", help="等長的人工修正陣列 JSON 檔；保留 json-file 原始 AI 值")
    parser.add_argument("--commit", action="store_true", help="經使用者確認後才加上此旗標")
    parser.add_argument("--request-id", help="確認匯入必填；重試沿用同一 ID")
    args = parser.parse_args()
    if args.commit and not args.request_id:
        parser.error("--commit 時必須提供 --request-id")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        request = {"json_text": Path(args.json_file).read_text(encoding="utf-8-sig")}
        if args.metadata_file:
            request["metadata"] = json.loads(Path(args.metadata_file).read_text(encoding="utf-8-sig"))
        elif args.raw_text_file:
            request["metadata"] = [{"raw_text": Path(args.raw_text_file).read_text(encoding="utf-8-sig")}]
        if args.edits_file:
            request["edits"] = json.loads(Path(args.edits_file).read_text(encoding="utf-8-sig"))
        service = HousingService(args.db_path)
        result = service.preview(request)
        if args.commit:
            result = service.commit({**request, "request_id": args.request_id})
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        if result.get("can_commit") is False:
            sys.exit(1)
    except HousingError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"輸入檔案無法讀取：{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
