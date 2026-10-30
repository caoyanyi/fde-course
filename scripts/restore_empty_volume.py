#!/usr/bin/env python3
"""Restore into an EMPTY volume only; never overwrite an existing learning database."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from configure import load_env

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="将备份恢复到空数据卷，不覆盖已有学习数据")
parser.add_argument("backup_directory", type=Path)
parser.add_argument("--skip-build", action="store_true", help="已有当前项目镜像时跳过构建")
parser.add_argument("--project-name", help="同机并存时指定新的 Compose 项目名，并写入 .env")
args = parser.parse_args()
if args.project_name and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", args.project_name):
    parser.error("项目名需以小写字母/数字开头，只含小写字母、数字、下划线、短横线")
source = args.backup_directory.resolve()
archive = source / "data.tar.gz"
environment = source / ".env"
if not archive.is_file() or not environment.is_file():
    raise SystemExit("备份目录需要同时包含 data.tar.gz 与 .env。")
with tarfile.open(archive, "r:gz") as handle:
    for entry in handle:
        name = Path(entry.name)
        if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != "data":
            raise SystemExit("备份包含越界路径，已停止。")
        if not entry.isfile() and not entry.isdir():
            raise SystemExit("备份包含符号链接或特殊文件，已停止。")
if (ROOT / ".env").exists():
    raise SystemExit("当前目录已有 .env。请使用一个新的解压目录/Compose 项目恢复，避免覆盖现有密钥。")
shutil.copy2(environment, ROOT / ".env")
(ROOT / ".env").chmod(0o600)
operation_env = os.environ.copy()
if args.project_name:
    restored = load_env(ROOT / ".env")
    restored["COMPOSE_PROJECT_NAME"] = args.project_name
    (ROOT / ".env").write_text("\n".join(f"{key}={value}" for key, value in restored.items()) + "\n", encoding="utf-8")
    operation_env["COMPOSE_PROJECT_NAME"] = args.project_name
if not args.skip_build:
    subprocess.run(["docker", "compose", "build"], cwd=ROOT, env=operation_env, check=True)
code = """
import pathlib,sys,tarfile
target=pathlib.Path('/app/data')
if any(target.iterdir()):
    sys.exit('目标数据卷不是空卷，恢复已停止；现有数据未修改。')
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz') as archive:
    archive.extractall('/app',filter='data')
print('数据库与附件已恢复。')
"""
try:
    with archive.open("rb") as input_file:
        subprocess.run(["docker", "compose", "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-c", code], cwd=ROOT, env=operation_env, stdin=input_file, check=True)
except Exception:
    print("恢复未完成。.env 已从备份复制，请先核实原因；不要重新生成 APP_MASTER_KEY。")
    raise
print("恢复完成。按需运行 configure.py 修改域名（它保留密钥），然后 docker compose up -d。")
