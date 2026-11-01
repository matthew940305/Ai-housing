"""每次操作短連線；交易 context 負責 commit / rollback 與統一錯誤。"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .errors import HousingError


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


class SQLiteStore:
    def __init__(self, path):
        if str(path) == ":memory:":
            raise HousingError("DATABASE_ERROR", "請使用檔案資料庫路徑，以支援重連持久保存。", status=500)
        self.path = Path(path).resolve()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HousingError("DATABASE_ERROR", "無法建立資料庫目錄。", status=500) from exc
        with self.connection(write=True) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS properties (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS import_requests (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, property_ids TEXT NOT NULL, wrapper_metadata TEXT NOT NULL)")

    @contextmanager
    def connection(self, *, write=False):
        conn = None
        try:
            conn = sqlite3.connect(self.path, timeout=5)
            conn.row_factory = sqlite3.Row
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except sqlite3.Error as exc:
            if conn:
                conn.rollback()
            raise HousingError("DATABASE_ERROR", "資料庫操作失敗，交易已回滾；請檢查路徑、權限或稍後重試。", status=500) from exc
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    @staticmethod
    def all(conn):
        return [json.loads(row["document"]) for row in conn.execute("SELECT document FROM properties ORDER BY rowid")]

    @staticmethod
    def get(conn, property_id):
        row = conn.execute("SELECT document FROM properties WHERE id = ?", (property_id,)).fetchone()
        if row is None:
            raise HousingError("PROPERTY_NOT_FOUND", "找不到指定房源。", status=404)
        return json.loads(row["document"])

    @staticmethod
    def insert(conn, prop):
        conn.execute("INSERT INTO properties (id, document) VALUES (?, ?)", (prop["id"], dumps(prop)))

    @staticmethod
    def update(conn, prop):
        conn.execute("UPDATE properties SET document = ? WHERE id = ?", (dumps(prop), prop["id"]))
