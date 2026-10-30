#!/usr/bin/env python3
"""Make a consistent stopped-app backup, including the encryption key in .env."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
environment = ROOT / ".env"
if not environment.is_file():
    raise SystemExit("未找到 .env，请在已配置的部署目录运行此脚本。")
destination = ROOT / "backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
destination.mkdir(parents=True, mode=0o700)
destination.parent.chmod(0o700)
shutil.copy2(environment, destination / ".env")
(destination / ".env").chmod(0o600)
compose = ["docker", "compose"]
subprocess.run(compose + ["stop", "app"], cwd=ROOT, check=True)
archive = destination / "data.tar.gz"
try:
    descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        subprocess.run(compose + [
            "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-c",
            "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); t.add('/app/data',arcname='data'); t.close()",
        ], cwd=ROOT, stdout=output, check=True)
except Exception:
    archive.unlink(missing_ok=True)
    raise
finally:
    subprocess.run(compose + ["up", "-d", "app"], cwd=ROOT, check=True)
print(f"备份完成：{destination}")
print("此目录同时含数据库、附件和密钥，请整体保管。恢复仅针对空数据卷，参见 README。")
