#!/usr/bin/env python3
"""Intentionally reveal the one-time setup secret only in the owner's local terminal."""
from configure import ROOT, load_env

token = load_env(ROOT / ".env").get("APP_SETUP_TOKEN")
if not token:
    raise SystemExit("请先运行 python3 scripts/configure.py")
print(token)
