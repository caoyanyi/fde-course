"""Check the backup boundary that prevents unintentional database migrations."""
import importlib.util
from pathlib import Path
import stat
import subprocess

import pytest


spec = importlib.util.spec_from_file_location("fde_backup", Path(__file__).resolve().parents[1] / "scripts/backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def prepare(tmp_path, monkeypatch, *, running=True, existing=True, fail=False):
    (tmp_path / ".env").write_text("APP_MASTER_KEY=private-test-value\n", encoding="utf-8")
    calls = []

    def run(command, **kwargs):
        calls.append(command[2:])
        if command[2] == "ps":
            present = existing if "--all" in command else running
            return subprocess.CompletedProcess(command, 0, "container-id\n" if present else "", "")
        if command[2] == "run":
            kwargs["stdout"].write(b"archive-test-bytes")
            if fail:
                raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(backup.subprocess, "run", run)
    return calls


def test_regular_backup_resumes_original_container_and_keeps_keys(tmp_path, monkeypatch):
    calls = prepare(tmp_path, monkeypatch)
    dest = backup.create_backup(tmp_path)
    assert [c[0] for c in calls] == ["ps", "ps", "stop", "run", "start"]
    assert (dest / ".env").read_bytes() == (tmp_path / ".env").read_bytes()
    assert stat.S_IMODE((dest / ".env").stat().st_mode) == 0o600
    assert stat.S_IMODE((dest / "data.tar.gz").stat().st_mode) == 0o600
    assert "--entrypoint" in calls[3] and "python" in calls[3]


def test_upgrade_backup_stays_stopped(tmp_path, monkeypatch):
    calls = prepare(tmp_path, monkeypatch)
    backup.create_backup(tmp_path, keep_stopped=True)
    assert [c[0] for c in calls] == ["ps", "ps", "stop", "run"]


def test_failed_backup_resumes_old_container_and_removes_partial_archive(tmp_path, monkeypatch):
    calls = prepare(tmp_path, monkeypatch, fail=True)
    with pytest.raises(subprocess.CalledProcessError):
        backup.create_backup(tmp_path, keep_stopped=True)
    assert calls[-1] == ["start", "app"]
    assert not list((tmp_path / "backups").glob("*/data.tar.gz"))
    assert all(c[0] != "up" for c in calls)


def test_previously_stopped_app_is_not_started(tmp_path, monkeypatch):
    calls = prepare(tmp_path, monkeypatch, running=False)
    backup.create_backup(tmp_path)
    assert [c[0] for c in calls] == ["ps", "ps", "run"]


def test_wrong_compose_project_cannot_create_empty_backup(tmp_path, monkeypatch):
    calls = prepare(tmp_path, monkeypatch, existing=False)
    with pytest.raises(RuntimeError, match="Compose"):
        backup.create_backup(tmp_path, keep_stopped=True)
    assert len(calls) == 1
    assert not (tmp_path / "backups").exists()
