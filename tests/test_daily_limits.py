"""Exercise the explicit upgrade boundary with real SQLite and a simulated Docker CLI."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys

import pytest


spec = importlib.util.spec_from_file_location("fde_daily_limits", Path(__file__).resolve().parents[1] / "scripts/set_daily_limits.py")
limits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(limits)
REAL_RUN = subprocess.run
PRIVATE_ENV = (
    b"# Keep this deployment and its exact keys\r\n"
    b"APP_MASTER_KEY='private-test-key-with-$-and-#'\r\n"
    b"APP_SETUP_TOKEN=private-setup-test-token\r\n"
    b"COMPOSE_PROJECT_NAME=existing-fde\r\n"
    b"PUBLIC_ORIGIN=https://learn.example.com\r\n"
    b"MAX_REVIEWS_PER_DAY=30\r\n"
    b"MAX_MATERIALS_PER_DAY=30\r\n"
    b"WEB_PORT=18080"
)


def database(tmp_path, *, version=2, first_role="admin"):
    path = tmp_path / "learning.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE, role TEXT,
                password_hash TEXT, review_daily_limit INTEGER, material_daily_limit INTEGER
            );
            CREATE TABLE reviews (id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE materials (id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER);
            INSERT INTO users VALUES(2,'student','learner','student-original-hash',17,9);
            INSERT INTO reviews VALUES('used-review','completed');
            INSERT INTO materials VALUES('used-material','failed');
            INSERT INTO sessions VALUES('existing-session',1);
        """)
        conn.execute("INSERT INTO users VALUES(1,'owner',?,'original-hash',30,30)", (first_role,))
        conn.execute(f"PRAGMA user_version={version}")
    return path


def snapshot(path):
    with sqlite3.connect(path) as conn:
        return {name: conn.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
                for name in ("users", "reviews", "materials", "sessions")}


def execute_database(path, *, limit=100, username=None, all_users=False):
    return REAL_RUN([sys.executable, "-c", limits.DATABASE_CODE, str(path)],
                    input=json.dumps({"limit": limit, "username": username, "all_users": all_users}),
                    text=True, capture_output=True)


def docker(tmp_path, monkeypatch, path, *, existing=True, after_update=None, transport_error=None):
    """Replace only Docker transport; execute the actual image helper locally."""
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[:2] == ["docker", "compose"]
        assert kwargs["capture_output"] and kwargs["text"]
        assert kwargs["cwd"] == tmp_path
        if command[2] == "ps":
            assert command[3:] == ["--all", "--quiet", "app"]
            return subprocess.CompletedProcess(command, 0, "existing-app-id\n" if existing else "", "")
        assert command[2:10] == ["run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-c"]
        assert command[-1] == "/app/data/learning.sqlite3"
        result = REAL_RUN([sys.executable, "-c", command[10], str(path)],
                          input=kwargs["input"], text=True, capture_output=True)
        if after_update and result.returncode == 0:
            after_update()
        if transport_error and result.returncode == 0:
            return subprocess.CompletedProcess(command, 1, "", transport_error)
        return result

    monkeypatch.setattr(limits.subprocess, "run", run)
    return calls


def test_explicit_update_preserves_keys_usage_and_other_accounts_on_rerun(tmp_path, monkeypatch, capsys):
    path = database(tmp_path)
    before = snapshot(path)
    env = tmp_path / ".env"
    env.write_bytes(PRIVATE_ENV)
    calls = docker(tmp_path, monkeypatch, path)
    for _ in range(2):
        assert limits.set_daily_limits(tmp_path) == {"updated_accounts": 1, "limit": 100}
    assert env.read_bytes() == PRIVATE_ENV.replace(b"MAX_REVIEWS_PER_DAY=30", b"MAX_REVIEWS_PER_DAY=100").replace(b"MAX_MATERIALS_PER_DAY=30", b"MAX_MATERIALS_PER_DAY=100")
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    after = snapshot(path)
    assert after["users"][0] == (1, "owner", "admin", "original-hash", 100, 100)
    assert after["users"][1] == before["users"][1]
    assert {k: v for k, v in after.items() if k != "users"} == {k: v for k, v in before.items() if k != "users"}
    assert [command[2] for command in calls] == ["ps", "run", "ps", "run"]
    assert not list(tmp_path.glob(".env-limits-*"))
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("target,count,expected", [
    ({"username": "student"}, 1, [(30, 30), (100, 100)]),
    ({"all_users": True}, 2, [(100, 100), (100, 100)]),
])
def test_explicit_account_selection(tmp_path, monkeypatch, target, count, expected):
    path = database(tmp_path)
    (tmp_path / ".env").write_bytes(PRIVATE_ENV)
    docker(tmp_path, monkeypatch, path)
    assert limits.set_daily_limits(tmp_path, **target)["updated_accounts"] == count
    assert [row[-2:] for row in snapshot(path)["users"]] == expected


@pytest.mark.parametrize("version", [0, 1, 999])
def test_unmigrated_or_future_database_cannot_change_env_or_records(tmp_path, monkeypatch, version):
    path = database(tmp_path, version=version)
    before = snapshot(path)
    env = tmp_path / ".env"
    env.write_bytes(PRIVATE_ENV)
    docker(tmp_path, monkeypatch, path)
    with pytest.raises(RuntimeError, match="schema 2"):
        limits.set_daily_limits(tmp_path)
    assert env.read_bytes() == PRIVATE_ENV
    assert snapshot(path) == before
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version
    assert not list(tmp_path.glob(".env-limits-*"))


@pytest.mark.parametrize("target,first_role", [
    ({"username": "missing-user"}, "admin"), ({}, "learner"),
])
def test_missing_target_cannot_change_environment_or_other_accounts(tmp_path, monkeypatch, target, first_role):
    path = database(tmp_path, first_role=first_role)
    before = snapshot(path)
    (tmp_path / ".env").write_bytes(PRIVATE_ENV)
    docker(tmp_path, monkeypatch, path)
    with pytest.raises(RuntimeError, match="没有找到目标账号"):
        limits.set_daily_limits(tmp_path, **target)
    assert snapshot(path) == before
    assert (tmp_path / ".env").read_bytes() == PRIVATE_ENV


def test_wrong_compose_project_does_not_run_container_or_write_env(tmp_path, monkeypatch):
    path = database(tmp_path)
    before = snapshot(path)
    (tmp_path / ".env").write_bytes(PRIVATE_ENV)
    calls = docker(tmp_path, monkeypatch, path, existing=False)
    with pytest.raises(RuntimeError, match="Compose"):
        limits.set_daily_limits(tmp_path)
    assert len(calls) == 1 and calls[0][2] == "ps"
    assert (tmp_path / ".env").read_bytes() == PRIVATE_ENV
    assert snapshot(path) == before
    assert not list(tmp_path.glob(".env-limits-*"))


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_empty_database_is_not_created_or_migrated(tmp_path, missing):
    path = tmp_path / "empty.sqlite3"
    if not missing:
        path.touch()
    result = execute_database(path)
    assert result.returncode == 2
    if missing:
        assert "未找到已有数据库" in result.stderr and not path.exists()
    else:
        assert "schema 2" in result.stderr and path.stat().st_size == 0


def test_invalid_users_schema_and_database_write_failure_roll_back(tmp_path):
    path = database(tmp_path)
    before = snapshot(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER reject_quota BEFORE UPDATE OF review_daily_limit ON users BEGIN SELECT RAISE(ABORT,'private database message'); END")
    result = execute_database(path)
    assert result.returncode == 2 and "数据库额度更新失败" in result.stderr
    assert "private database message" not in result.stderr and snapshot(path) == before
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER reject_quota")
        conn.execute("ALTER TABLE users DROP COLUMN material_daily_limit")
    result = execute_database(path)
    assert result.returncode == 2 and "账号表结构不匹配" in result.stderr


def test_concurrent_environment_edit_is_retained_and_partial_result_is_explicit(tmp_path, monkeypatch):
    path = database(tmp_path)
    env = tmp_path / ".env"
    env.write_bytes(PRIVATE_ENV)
    concurrent = PRIVATE_ENV + b"\r\nNEW_SETTING=preserve-concurrent-change\r\n"
    docker(tmp_path, monkeypatch, path, after_update=lambda: env.write_bytes(concurrent))
    with pytest.raises(RuntimeError, match="账号额度已更新，但 .env 更新未完成"):
        limits.set_daily_limits(tmp_path)
    assert env.read_bytes() == concurrent
    assert snapshot(path)["users"][0][-2:] == (100, 100)
    assert not list(tmp_path.glob(".env-limits-*"))


def test_committed_database_with_lost_transport_receipt_is_uncertain_and_retry_safe(tmp_path, monkeypatch, capsys):
    path = database(tmp_path)
    before = snapshot(path)
    env = tmp_path / ".env"
    env.write_bytes(PRIVATE_ENV)
    private_message = "Docker connection lost: private-transport-secret"
    calls = docker(tmp_path, monkeypatch, path, transport_error=private_message)
    with pytest.raises(RuntimeError, match="数据库更新结果未确认") as error:
        limits.set_daily_limits(tmp_path)
    assert ".env 未修改" in str(error.value)
    assert "重复执行不会重置当天已用次数" in str(error.value)
    assert "private-transport-secret" not in str(error.value)
    assert env.read_bytes() == PRIVATE_ENV
    after = snapshot(path)
    assert after["users"][0][-2:] == (100, 100)
    assert after["users"][1] == before["users"][1]
    assert {k: v for k, v in after.items() if k != "users"} == {k: v for k, v in before.items() if k != "users"}
    assert [command[2] for command in calls] == ["ps", "run"]
    assert not list(tmp_path.glob(".env-limits-*"))
    captured = capsys.readouterr()
    assert "private-transport-secret" not in captured.out + captured.err
    docker(tmp_path, monkeypatch, path)
    assert limits.set_daily_limits(tmp_path) == {"updated_accounts": 1, "limit": 100}
    assert snapshot(path) == after
    assert env.read_bytes() == PRIVATE_ENV.replace(b"MAX_REVIEWS_PER_DAY=30", b"MAX_REVIEWS_PER_DAY=100").replace(b"MAX_MATERIALS_PER_DAY=30", b"MAX_MATERIALS_PER_DAY=100")


def test_missing_keys_are_appended_and_duplicate_keys_refused():
    assert limits.replace_limits(b"SECRET=keep", 100) == b"SECRET=keep\nMAX_REVIEWS_PER_DAY=100\nMAX_MATERIALS_PER_DAY=100\n"
    with pytest.raises(ValueError, match="重复"):
        limits.replace_limits(b"MAX_REVIEWS_PER_DAY=30\nMAX_REVIEWS_PER_DAY=25\n", 100)


@pytest.mark.parametrize("invalid", [-1, 1001, True])
def test_invalid_limits_do_not_edit_the_database(tmp_path, invalid):
    path = database(tmp_path)
    before = snapshot(path)
    with pytest.raises(ValueError):
        limits.replace_limits(PRIVATE_ENV, invalid)
    assert execute_database(path, limit=invalid).returncode == 2
    assert snapshot(path) == before


@pytest.mark.parametrize("value", [0, 1000])
def test_supported_limit_boundaries(tmp_path, value):
    path = database(tmp_path)
    assert execute_database(path, limit=value).returncode == 0
    assert snapshot(path)["users"][0][-2:] == (value, value)
