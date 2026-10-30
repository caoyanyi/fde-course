"""Upgrade real v1 schema and verify ownership/data preservation and rollback."""
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import Database, SCHEMA_VERSION
from app.config import Settings
from app.main import create_app
from app.security import hash_password
from .conftest import TASK


V1_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY CHECK(id=1),username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),csrf_token TEXT NOT NULL,expires_at INTEGER NOT NULL);
CREATE TABLE progress (task_id TEXT PRIMARY KEY,status TEXT NOT NULL,actual_hours REAL,notes TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
CREATE TABLE submissions (id TEXT PRIMARY KEY,task_id TEXT NOT NULL,version INTEGER NOT NULL,content TEXT NOT NULL,evidence_notes TEXT NOT NULL,created_at TEXT NOT NULL,static_checks TEXT NOT NULL,course_version TEXT NOT NULL,task_snapshot TEXT NOT NULL,UNIQUE(task_id,version));
CREATE TABLE files (id TEXT PRIMARY KEY,submission_id TEXT NOT NULL REFERENCES submissions(id),filename TEXT NOT NULL,stored_name TEXT NOT NULL UNIQUE,size INTEGER NOT NULL,sha256 TEXT NOT NULL,extracted_text TEXT NOT NULL,truncated INTEGER NOT NULL,extraction_note TEXT NOT NULL);
CREATE TABLE ai_settings (id INTEGER PRIMARY KEY CHECK(id=1),provider_label TEXT NOT NULL,base_url TEXT NOT NULL,model TEXT NOT NULL,api_key_cipher TEXT,max_tokens INTEGER NOT NULL,timeout_seconds INTEGER NOT NULL,temperature REAL NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE reviews (id TEXT PRIMARY KEY,submission_id TEXT NOT NULL REFERENCES submissions(id),status TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT,error TEXT,model TEXT NOT NULL,provider_label TEXT NOT NULL,settings_snapshot TEXT NOT NULL,report TEXT,usage TEXT,prompt_version TEXT NOT NULL,data_consent_at TEXT NOT NULL);
CREATE INDEX reviews_submission_idx ON reviews(submission_id,created_at);
CREATE INDEX reviews_status_idx ON reviews(status);
CREATE INDEX submissions_task_idx ON submissions(task_id,version);
"""


def make_v1(tmp_path, *, corrupt=False):
    data = tmp_path / 'data'
    data.mkdir()
    (data/'uploads').mkdir()
    (data/'uploads'/'old.data').write_text('原附件', encoding='utf-8')
    db = Database(data/'learning.sqlite3')
    with sqlite3.connect(db.path) as conn:
        conn.executescript(V1_SCHEMA)
        conn.execute('INSERT INTO users VALUES(1,?,?,?)', ('owner',hash_password('original-password-123'),'2026-01-01T00:00:00+00:00'))
        conn.execute("INSERT INTO progress VALUES('w01-t01','completed',8.5,'原备注','2026-01-01')")
        conn.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)', ('sub-old','w01-t01',3,'原作业','原证据','2026-01-01','[]','old-course',json.dumps(TASK)))
        conn.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?)', ('file-old','missing' if corrupt else 'sub-old','old.txt','old.data',9,'original-hash','原附件',0,'原提取说明'))
        conn.execute("INSERT INTO sessions VALUES('old-session',1,'old-csrf',9999999999)")
        conn.execute("INSERT INTO ai_settings VALUES(1,'old-provider','https://example.com/v1','old-model','original-cipher',3000,90,0.2,'2026-01-01')")
        conn.execute("INSERT INTO reviews VALUES('review-old','sub-old','completed','2026-01-01','2026-01-01',NULL,'old-model','old-provider','{}','{\"total_score\":73}','{}','old-prompt','2026-01-01')")
    return db


def test_v1_upgrade_preserves_all_records_and_is_idempotent(tmp_path):
    db = make_v1(tmp_path)
    db.initialize()
    backups = list((db.path.parent/'migration-backups').glob('*.sqlite3'))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert db.path.stat().st_mode & 0o777 == 0o600
    with db.connect() as c:
        user = dict(c.execute('SELECT * FROM users').fetchone())
        assert user['role'] == 'admin' and user['username'] == 'owner'
        assert user['must_change_password'] == 0
        assert user['review_daily_limit'] == user['material_daily_limit'] == 100
        assert c.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
        assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
        p = dict(c.execute('SELECT * FROM progress').fetchone())
        assert p['user_id'] == 1 and p['notes'] == '原备注' and p['actual_hours'] == 8.5
        s = dict(c.execute('SELECT * FROM submissions').fetchone())
        assert s['id'] == 'sub-old' and s['user_id'] == 1 and s['version'] == 3 and s['content'] == '原作业' and s['material_pack_id'] is None
        assert c.execute('SELECT sha256 FROM files').fetchone()[0] == 'original-hash'
        assert json.loads(c.execute('SELECT report FROM reviews').fetchone()[0])['total_score'] == 73
        ai = dict(c.execute('SELECT * FROM ai_settings').fetchone())
        assert ai['api_key_cipher'] == 'original-cipher' and ai['material_max_tokens'] == 6000
        c.execute("INSERT INTO users(username,password_hash,created_at) VALUES('new-user','hash','2026-01-02')")
        new_user = c.execute("SELECT * FROM users WHERE username='new-user'").fetchone()
        assert new_user['id'] == 2
        assert new_user['review_daily_limit'] == new_user['material_daily_limit'] == 100
        c.execute("INSERT INTO progress VALUES(2,'w01-t01','in_progress',1,'new','now')")
        c.execute("INSERT INTO submissions(id,user_id,task_id,version,content,evidence_notes,created_at,static_checks,course_version,task_snapshot) VALUES('new-sub',2,'w01-t01',3,'new','','now','[]','v1','{}')")
    assert (db.path.parent/'uploads'/'old.data').read_text() == '原附件'
    with sqlite3.connect(backups[0]) as c:
        assert 'role' not in {r[1] for r in c.execute('PRAGMA table_info(users)')}
        assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1
    db.initialize()
    assert len(list((db.path.parent/'migration-backups').glob('*.sqlite3'))) == 1


def test_original_password_and_owned_api_work_after_upgrade(tmp_path):
    db = make_v1(tmp_path)
    course = tmp_path/'course.json'
    course.write_text(json.dumps({'version':'new','weeks':[{'tasks':[TASK]}]}))
    config = Settings(data_dir=db.path.parent,course_path=course,master_key='migration-test-master-key-minimum-32',secure_cookie=False,public_origin='http://testserver',start_worker=False)
    with TestClient(create_app(config)) as client:
        login=client.post('/api/auth/login',headers={'X-FDE-Client':'web'},json={'username':'owner','password':'original-password-123'})
        assert login.status_code == 200 and login.json()['user']['role'] == 'admin'
        client.headers.update({'X-FDE-Client':'web','X-CSRF-Token':login.json()['csrf_token']})
        assert client.get('/api/submissions/sub-old').json()['content'] == '原作业'
        assert client.get('/api/files/file-old').content.decode() == '原附件'
        assert client.get('/api/course').json()['progress']['w01-t01']['status'] == 'completed'
        submitted=client.post('/api/tasks/w01-t01/submissions',data={'content':'升级后提交'})
        assert submitted.status_code == 201 and submitted.json()['version'] == 4


def test_failed_migration_rolls_back_and_keeps_backup(tmp_path):
    db = make_v1(tmp_path,corrupt=True)
    with pytest.raises(RuntimeError,match='关联校验失败'):
        db.initialize()
    with sqlite3.connect(db.path) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 0
        assert 'role' not in {r[1] for r in c.execute('PRAGMA table_info(users)')}
        assert c.execute('SELECT COUNT(*) FROM submissions').fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='users_v2'").fetchone()
    assert len(list((db.path.parent/'migration-backups').glob('*.sqlite3'))) == 1


def test_future_database_refused_without_mutation(tmp_path):
    db = Database(tmp_path/'future.sqlite3')
    with sqlite3.connect(db.path) as c:
        c.execute('PRAGMA user_version=999')
        c.execute('CREATE TABLE future_data(value TEXT)')
        c.execute("INSERT INTO future_data VALUES('keep')")
    with pytest.raises(RuntimeError,match='高于'):
        db.initialize()
    with sqlite3.connect(db.path) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 999
        assert c.execute('SELECT value FROM future_data').fetchone()[0] == 'keep'
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
