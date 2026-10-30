from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY CHECK(id = 1), username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
    task_id TEXT PRIMARY KEY, status TEXT NOT NULL,
    actual_hours REAL, notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, version INTEGER NOT NULL,
    content TEXT NOT NULL, evidence_notes TEXT NOT NULL, created_at TEXT NOT NULL,
    static_checks TEXT NOT NULL, course_version TEXT NOT NULL,
    task_snapshot TEXT NOT NULL,
    UNIQUE(task_id, version)
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
    temperature REAL NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id),
    status TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT,
    error TEXT, model TEXT NOT NULL, provider_label TEXT NOT NULL,
    settings_snapshot TEXT NOT NULL,
    report TEXT, usage TEXT, prompt_version TEXT NOT NULL,
    data_consent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_submission_idx ON reviews(submission_id, created_at);
CREATE INDEX IF NOT EXISTS reviews_status_idx ON reviews(status);
CREATE INDEX IF NOT EXISTS submissions_task_idx ON submissions(task_id, version);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
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
