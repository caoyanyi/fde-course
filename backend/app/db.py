from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


SCHEMA_VERSION = 2
USERS_SQL = """CREATE TABLE {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL, created_at TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'learner' CHECK(role IN ('admin','learner')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN (0,1)),
    review_daily_limit INTEGER NOT NULL DEFAULT 10 CHECK(review_daily_limit >= 0),
    material_daily_limit INTEGER NOT NULL DEFAULT 5 CHECK(material_daily_limit >= 0)
)"""
PROGRESS_SQL = """CREATE TABLE {name} (
    user_id INTEGER NOT NULL REFERENCES users(id), task_id TEXT NOT NULL,
    status TEXT NOT NULL, actual_hours REAL, notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id,task_id)
)"""
SUBMISSIONS_SQL = """CREATE TABLE {name} (
    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    task_id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
    evidence_notes TEXT NOT NULL, created_at TEXT NOT NULL, static_checks TEXT NOT NULL,
    course_version TEXT NOT NULL, task_snapshot TEXT NOT NULL, material_pack_id TEXT,
    UNIQUE(user_id,task_id,version)
)"""
SCHEMA = ";\n".join([
    USERS_SQL.format(name="IF NOT EXISTS users"),
    PROGRESS_SQL.format(name="IF NOT EXISTS progress"),
    SUBMISSIONS_SQL.format(name="IF NOT EXISTS submissions"),
]) + ";\n" + """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id),
    filename TEXT NOT NULL, stored_name TEXT NOT NULL UNIQUE, size INTEGER NOT NULL,
    sha256 TEXT NOT NULL, extracted_text TEXT NOT NULL, truncated INTEGER NOT NULL,
    extraction_note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1), provider_label TEXT NOT NULL,
    base_url TEXT NOT NULL, model TEXT NOT NULL, api_key_cipher TEXT,
    max_tokens INTEGER NOT NULL, timeout_seconds INTEGER NOT NULL,
    temperature REAL NOT NULL, updated_at TEXT NOT NULL,
    material_max_tokens INTEGER NOT NULL DEFAULT 6000
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id),
    status TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT,
    error TEXT, model TEXT NOT NULL, provider_label TEXT NOT NULL,
    settings_snapshot TEXT NOT NULL,
    report TEXT, usage TEXT, prompt_version TEXT NOT NULL,
    data_consent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL REFERENCES users(id),
    target_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
    details TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
CREATE INDEX IF NOT EXISTS reviews_submission_idx ON reviews(submission_id, created_at);
CREATE INDEX IF NOT EXISTS reviews_status_idx ON reviews(status);
CREATE INDEX IF NOT EXISTS submissions_task_idx ON submissions(user_id,task_id,version);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def _create_schema(conn):
        # executescript() commits pending transactions; migration must stay atomic.
        for statement in SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)

    def _backup(self, conn) -> Path:
        directory = self.path.parent / "migration-backups"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        path = directory / f"v1-before-v2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{secrets.token_hex(3)}.sqlite3"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            with sqlite3.connect(path) as backup:
                conn.backup(backup)
                if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("迁移前数据库备份校验失败，停止升级")
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def _migrate_v1(self, conn):
        self._backup(conn)
        # Rebuild affected tables without renaming the old parent tables; child
        # FK declarations must keep pointing to users/submissions, not *_old.
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(USERS_SQL.format(name="users_v2"))
            conn.execute(PROGRESS_SQL.format(name="progress_v2"))
            conn.execute(SUBMISSIONS_SQL.format(name="submissions_v2"))
            conn.execute("INSERT INTO users_v2(id,username,password_hash,created_at,display_name,role,review_daily_limit,material_daily_limit) SELECT id,username,password_hash,created_at,username,'admin',30,30 FROM users")
            conn.execute("INSERT INTO progress_v2(user_id,task_id,status,actual_hours,notes,updated_at) SELECT 1,task_id,status,actual_hours,notes,updated_at FROM progress")
            conn.execute("INSERT INTO submissions_v2(id,user_id,task_id,version,content,evidence_notes,created_at,static_checks,course_version,task_snapshot) SELECT id,1,task_id,version,content,evidence_notes,created_at,static_checks,course_version,task_snapshot FROM submissions")
            for name in ("users", "progress", "submissions"):
                conn.execute(f"DROP TABLE {name}")
                conn.execute(f"ALTER TABLE {name}_v2 RENAME TO {name}")
            conn.execute("ALTER TABLE ai_settings ADD COLUMN material_max_tokens INTEGER NOT NULL DEFAULT 6000")
            conn.execute("DELETE FROM sessions")
            self._create_schema(conn)
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("迁移后数据关联校验失败，已回滚；请检查原数据库")
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("数据库版本高于此程序支持的版本，请使用相应新版源码；禁止降级启动")
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
            if exists:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
                if "role" not in columns:
                    self._migrate_v1(conn)
                elif version != SCHEMA_VERSION:
                    raise RuntimeError("数据库结构与版本不匹配，停止启动以保护已有数据")
            else:
                conn.execute("BEGIN IMMEDIATE")
                self._create_schema(conn)
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                conn.commit()
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("数据库外键完整性检查失败")
            conn.execute("PRAGMA journal_mode=WAL")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
