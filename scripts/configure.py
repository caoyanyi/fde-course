#!/usr/bin/env python3
"""Create or update private deployment settings without rotating existing keys."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def domain_name(value: str) -> str:
    value = value.lower().rstrip(".")
    if len(value) > 253 or "." not in value:
        raise argparse.ArgumentTypeError("请输入完整域名，例如 learn.example.com")
    labels = value.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise argparse.ArgumentTypeError("只填写域名，不含 https://、路径或端口；国际域名请使用 punycode")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="生成部署配置；再次运行保留账户数据和现有加密密钥")
    parser.add_argument("--domain", type=domain_name, help="正式 HTTPS 域名")
    parser.add_argument("--port", type=int, help="宿主机回环端口，默认 18080")
    parser.add_argument("--local", action="store_true", help="明确切换回本机 HTTP 模式")
    args = parser.parse_args()
    if args.domain and args.local:
        parser.error("--domain 与 --local 不能同时指定")
    path = ROOT / ".env"
    values = load_env(path)
    port = args.port if args.port is not None else int(values.get("WEB_PORT", "18080"))
    if not 1024 <= port <= 65535:
        parser.error("--port 需要在 1024–65535 之间")
    values.setdefault("APP_SETUP_TOKEN", secrets.token_urlsafe(32))
    values.setdefault("APP_MASTER_KEY", secrets.token_urlsafe(48))
    for key, size in [("APP_SETUP_TOKEN", 32), ("APP_MASTER_KEY", 48)]:
        if not values[key]:
            values[key] = secrets.token_urlsafe(size)
    if len(values["APP_MASTER_KEY"]) < 32:
        parser.error("现有 APP_MASTER_KEY 太短。请确认是否已有加密数据后手动处理；本脚本不会覆盖密钥。")
    values["WEB_PORT"] = str(port)
    values.setdefault("BIND_ADDRESS", "127.0.0.1")
    values.setdefault("MAX_REVIEWS_PER_DAY", "100")
    values.setdefault("MAX_MATERIALS_PER_DAY", "100")
    values.setdefault("AI_PRIVATE_HOST_ALLOWLIST", "")
    if args.domain:
        values["PUBLIC_ORIGIN"] = f"https://{args.domain}"
        values["SESSION_COOKIE_SECURE"] = "true"
    elif args.local or "PUBLIC_ORIGIN" not in values:
        values["PUBLIC_ORIGIN"] = f"http://localhost:{port}"
        values["SESSION_COOKIE_SECURE"] = "false"
    elif args.port and values["PUBLIC_ORIGIN"].startswith("http://localhost:"):
        values["PUBLIC_ORIGIN"] = f"http://localhost:{port}"
    values.setdefault("SESSION_COOKIE_SECURE", "true")
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or any(c in value for c in "\r\n\x00"):
            parser.error("现有配置包含无效内容，请检查 .env")
    content = "# Private deployment settings. Back up together with the data volume.\n"
    content += "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    fd, temp = tempfile.mkstemp(prefix=".env-write-", dir=ROOT)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print(f"配置已保存。访问地址：{values['PUBLIC_ORIGIN']}")
    print("首次开通令牌：在你的服务器终端运行 python3 scripts/show_setup_token.py 查看。")
    print("下一步：docker compose up -d --build")


if __name__ == "__main__":
    main()
