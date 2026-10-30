#!/usr/bin/env python3
"""Back up a quiescent data volume without accidentally starting new app code."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def create_backup(root: Path, *, keep_stopped: bool = False) -> Path:
    environment = root / ".env"
    if not environment.is_file():
        raise RuntimeError("未找到 .env，请在已有部署的代码目录运行备份。")
    compose = ["docker", "compose"]
    existing = subprocess.run(compose + ["ps", "--all", "--quiet", "app"],
                              cwd=root, capture_output=True, text=True, check=True)
    if not existing.stdout.strip():
        raise RuntimeError("未找到这个 Compose 项目的 app 容器。请核对原项目名，避免把新建空卷误当作已有数据备份。")
    running = subprocess.run(compose + ["ps", "--status", "running", "--quiet", "app"],
                             cwd=root, capture_output=True, text=True, check=True)
    was_running = bool(running.stdout.strip())
    destination = root / "backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir(parents=True, mode=0o700)
    destination.parent.chmod(0o700)
    shutil.copy2(environment, destination / ".env")
    (destination / ".env").chmod(0o600)
    archive = destination / "data.tar.gz"
    stopped = False
    completed = False
    try:
        if was_running:
            subprocess.run(compose + ["stop", "app"], cwd=root, check=True)
            stopped = True
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            subprocess.run(compose + [
                "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-c",
                "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); t.add('/app/data',arcname='data'); t.close()",
            ], cwd=root, stdout=output, check=True)
        completed = True
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    finally:
        if stopped and (not keep_stopped or not completed):
            # start resumes the existing container; up might apply the new image.
            subprocess.run(compose + ["start", "app"], cwd=root, check=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="备份数据库、附件和原有加密配置")
    parser.add_argument("--keep-stopped", action="store_true",
                        help="成功后保持后端停止，适合随后升级；失败仍恢复原有运行状态")
    args = parser.parse_args()
    try:
        destination = create_backup(ROOT, keep_stopped=args.keep_stopped)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"备份未完成：{exc}") from exc
    print(f"备份完成：{destination}")
    print("请完整保存该目录中的 data.tar.gz 与 .env；备份包含密钥，请妥善保管。")
    if args.keep_stopped:
        print("后端保持停止。确认升级代码与配置后，运行 docker compose up -d。")


if __name__ == "__main__":
    main()
