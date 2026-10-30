"""Meaningful checks that deployment changes cannot silently rotate encryption keys."""
from pathlib import Path
import shutil
import stat
import subprocess
import sys


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "configure.py"


def sandbox(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    target = scripts / "configure.py"
    shutil.copy2(SOURCE, target)
    return target


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#"))


def test_new_config_is_private_and_origin_changes_preserve_keys(tmp_path):
    script = sandbox(tmp_path)
    result = run(script, "--domain", "learn.example.com")
    assert result.returncode == 0
    first = env(tmp_path / ".env")
    assert len(first["APP_MASTER_KEY"]) >= 32
    assert first["SESSION_COOKIE_SECURE"] == "true"
    assert first["MAX_REVIEWS_PER_DAY"] == "100"
    assert first["MAX_MATERIALS_PER_DAY"] == "100"
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600
    assert first["APP_MASTER_KEY"] not in result.stdout
    assert first["APP_SETUP_TOKEN"] not in result.stdout
    assert run(script, "--domain", "new.example.com", "--port", "18081").returncode == 0
    second = env(tmp_path / ".env")
    assert second["APP_MASTER_KEY"] == first["APP_MASTER_KEY"]
    assert second["APP_SETUP_TOKEN"] == first["APP_SETUP_TOKEN"]
    assert second["PUBLIC_ORIGIN"] == "https://new.example.com"
    assert second["WEB_PORT"] == "18081"


def test_reconfigure_preserves_explicit_daily_limits(tmp_path):
    script = sandbox(tmp_path)
    assert run(script, "--domain", "learn.example.com").returncode == 0
    config_path = tmp_path / ".env"
    original = config_path.read_text()
    config_path.write_text(original.replace("MAX_REVIEWS_PER_DAY=100", "MAX_REVIEWS_PER_DAY=30").replace(
        "MAX_MATERIALS_PER_DAY=100", "MAX_MATERIALS_PER_DAY=17",
    ))

    assert run(script, "--domain", "new.example.com").returncode == 0
    current = env(config_path)
    assert current["PUBLIC_ORIGIN"] == "https://new.example.com"
    assert current["MAX_REVIEWS_PER_DAY"] == "30"
    assert current["MAX_MATERIALS_PER_DAY"] == "17"


def test_invalid_domain_or_port_does_not_create_config(tmp_path):
    script = sandbox(tmp_path)
    assert run(script, "--domain", "https://example.com/path").returncode != 0
    assert run(script, "--port", "0").returncode != 0
    assert not (tmp_path / ".env").exists()


def test_explicit_local_mode_and_no_implicit_origin_reset(tmp_path):
    script = sandbox(tmp_path)
    assert run(script, "--domain", "learn.example.com").returncode == 0
    assert run(script).returncode == 0
    assert env(tmp_path / ".env")["PUBLIC_ORIGIN"] == "https://learn.example.com"
    assert run(script, "--local", "--port", "19080").returncode == 0
    current = env(tmp_path / ".env")
    assert current["PUBLIC_ORIGIN"] == "http://localhost:19080"
    assert current["SESSION_COOKIE_SECURE"] == "false"
