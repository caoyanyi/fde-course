from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque

from cryptography.fernet import Fernet

from .config import Settings


COOKIE_NAME = "fde_session"
PASSWORD_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def encryption(settings: Settings) -> Fernet:
    if settings.master_key:
        if len(settings.master_key) < 32:
            raise RuntimeError("APP_MASTER_KEY 至少需要 32 个字符")
        secret = settings.master_key.encode()
    else:
        path = settings.data_dir / "master.key"
        if not path.exists():
            # Exclusive create prevents concurrent initialization from replacing a key.
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(secrets.token_bytes(48))
            except FileExistsError:
                pass
        secret = path.read_bytes()
        path.chmod(0o600)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


class LoginLimiter:
    """Small single-process limiter; deployment proxy should also limit login traffic."""

    def __init__(self):
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        current = time.monotonic()
        with self._lock:
            # Bound memory for arbitrary clients and discard expired buckets.
            if len(self._attempts) > 10_000:
                self._attempts = defaultdict(deque, {
                    item: values for item, values in self._attempts.items()
                    if values and current - values[-1] < 900
                })
            if key not in self._attempts and len(self._attempts) >= 10_000:
                return False
            attempts = self._attempts[key]
            while attempts and current - attempts[0] >= 900:
                attempts.popleft()
            if len(attempts) >= 10:
                return False
            attempts.append(current)
            return True

    def clear(self, key: str):
        with self._lock:
            self._attempts.pop(key, None)
