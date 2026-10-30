#!/usr/bin/env python3
"""Explicitly update site and selected account quotas in an existing v1.1 deployment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
QUOTA_KEYS = ("MAX_REVIEWS_PER_DAY", "MAX_MATERIALS_PER_DAY")

# Standard library only: run under the existing app image without starting the
# application, running migrations, reading API keys, or resetting usage records.
DATABASE_CODE = r'''
import json,sqlite3,sys
from pathlib import Path

def update():
    path=Path(sys.argv[1])
    request=json.loads(sys.stdin.read())
    limit=request['limit']
    if type(limit) is not int or not 0 <= limit <= 1000:
        raise ValueError('额度必须在 0 到 1000 之间')
    if not path.is_file():
        raise ValueError('未找到已有数据库，拒绝创建或修改空卷')
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True,timeout=15)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute('PRAGMA busy_timeout=15000')
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('PRAGMA user_version').fetchone()[0] != 2:
            raise ValueError('数据库不是 v1.1 支持的 schema 2；请先完成迁移并启动新版，再调整额度')
        columns={r['name'] for r in conn.execute('PRAGMA table_info(users)')}
        if not {'id','username','role','review_daily_limit','material_daily_limit'}.issubset(columns):
            raise ValueError('账号表结构不匹配，已停止')
        if request.get('all_users'):
            where,args='1=1',()
        elif request.get('username'):
            where,args='username=?',(request['username'],)
        else:
            where,args="id=1 AND role='admin'",()
        ids=[r['id'] for r in conn.execute('SELECT id FROM users WHERE '+where,args)]
        if not ids:
            raise ValueError('没有找到目标账号；默认选择原管理员 id=1，可使用 --username 指定')
        conn.execute('UPDATE users SET review_daily_limit=?,material_daily_limit=? WHERE '+where,(limit,limit,*args))
        conn.commit()
        print(json.dumps({'updated_accounts':len(ids),'limit':limit}))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

try:
    update()
except ValueError as exc:
    print(str(exc),file=sys.stderr)
    sys.exit(2)
except Exception:
    print('数据库额度更新失败；未自动创建、迁移或清空数据库，请检查数据库状态后重试',file=sys.stderr)
    sys.exit(2)
'''


def replace_limits(content: bytes, limit: int) -> bytes:
    """Preserve all unrelated bytes, including original secrets and comments."""
    if type(limit) is not int or not 0 <= limit <= 1000:
        raise ValueError("额度必须在 0 到 1000 之间")
    value = content.decode("utf-8")
    newline = "\r\n" if "\r\n" in value else "\n"
    seen = set()
    output = []
    pattern = re.compile(r"^(\s*(?:export\s+)?)(MAX_REVIEWS_PER_DAY|MAX_MATERIALS_PER_DAY)\s*=.*$")
    for line in value.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        match = pattern.fullmatch(body)
        if not match:
            output.append(line)
            continue
        key = match.group(2)
        if key in seen:
            raise ValueError(f".env 中 {key} 重复，请先保留一个有效配置项")
        seen.add(key)
        ending = line[len(body):]
        output.append(f"{match.group(1)}{key}={limit}{ending}")
    result = "".join(output)
    for key in QUOTA_KEYS:
        if key not in seen:
            if result and not result.endswith(("\n", "\r")):
                result += newline
            result += f"{key}={limit}{newline}"
    return result.encode("utf-8")


def set_daily_limits(root: Path, limit: int = 100, *, username: str | None = None, all_users: bool = False) -> dict:
    if username is not None and not re.fullmatch(r"[A-Za-z0-9_-]{3,40}", username):
        raise ValueError("用户名必须是 3–40 位英文字母、数字、下划线或短横线")
    if username is not None and all_users:
        raise ValueError("--username 与 --all-users 不能同时指定")
    path = root / ".env"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("未找到普通文件 .env；请在已有部署代码目录运行，不能使用符号链接配置")
    original = path.read_bytes()
    updated = replace_limits(original, limit)
    compose = ["docker", "compose"]
    existing = subprocess.run(compose + ["ps", "--all", "--quiet", "app"], cwd=root,
                              capture_output=True, text=True, check=False)
    if existing.returncode != 0 or not existing.stdout.strip():
        raise RuntimeError("未找到这个 Compose 项目的 app 容器。请核对原项目名和 .env；没有修改额度。")

    # Finish all file preparation before committing account changes. Cross-file
    # and database writes cannot be one transaction; report a rare partial result
    # explicitly and allow safely rerunning this idempotent operation.
    descriptor, temporary = tempfile.mkstemp(prefix=".env-limits-", dir=root)
    database_updated = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != original:
            raise RuntimeError(".env 在操作期间发生变化，已停止；请核对后重新执行。")
        request = json.dumps({"limit": limit, "username": username, "all_users": all_users})
        result = subprocess.run(compose + ["run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-c", DATABASE_CODE, "/app/data/learning.sqlite3"],
                                cwd=root, input=request, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            # The helper emits only fixed validation messages, never .env or keys.
            message = result.stderr.strip().splitlines()
            safe = next((line for line in reversed(message) if line.startswith(("未找到已有数据库", "数据库不是 v1.1", "账号表结构不匹配", "没有找到目标账号", "数据库额度更新失败"))), None)
            raise RuntimeError(safe or "数据库更新结果未确认，.env 未修改；请核对后重新执行，重复执行不会重置当天已用次数。")
        database_updated = True
        receipt = json.loads(result.stdout.strip())
        if receipt.get("limit") != limit or type(receipt.get("updated_accounts")) is not int or receipt["updated_accounts"] < 1:
            raise RuntimeError("数据库更新回执无效")
        if path.is_symlink() or path.read_bytes() != original:
            raise RuntimeError(".env 在操作期间发生变化")
        os.replace(temporary, path)
        return receipt
    except Exception as exc:
        if database_updated:
            raise RuntimeError("账号额度已更新，但 .env 更新未完成。请核对配置后重新运行本命令；它不会重置当天已用次数。") from exc
        raise
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description="显式修改全站及目标账号每日评审、素材额度，不清空使用记录")
    parser.add_argument("--limit", type=int, default=100, help="两类额度相同，0–1000，默认 100")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--username", help="指定账号；省略时仅修改原管理员 id=1")
    target.add_argument("--all-users", action="store_true", help="明确把所有账号的两类额度改为指定值")
    args = parser.parse_args()
    try:
        result = set_daily_limits(ROOT, args.limit, username=args.username, all_users=args.all_users)
    except (ValueError, RuntimeError, OSError) as exc:
        raise SystemExit(f"额度调整未完成：{exc}") from exc
    print(f"全站每日评审和素材额度已写为 {args.limit} 次；已更新 {result['updated_accounts']} 个目标账号。")
    print("原有密钥和其他 .env 配置已保留，当天已用次数没有清空。")
    print("下一步运行 docker compose up -d，使全站环境配置生效；然后刷新账号页面。")


if __name__ == "__main__":
    main()
