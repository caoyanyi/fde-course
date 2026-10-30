from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "./data")))
    course_path: Path = field(default_factory=lambda: Path(os.getenv("COURSE_PATH", "../course/curriculum.json")))
    setup_token: str = field(default_factory=lambda: os.getenv("APP_SETUP_TOKEN", ""))
    master_key: str = field(default_factory=lambda: os.getenv("APP_MASTER_KEY", ""))
    public_origin: str = field(default_factory=lambda: os.getenv("PUBLIC_ORIGIN", "").rstrip("/"))
    secure_cookie: bool = field(default_factory=lambda: os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true")
    private_host_allowlist: tuple[str, ...] = field(default_factory=lambda: tuple(
        host.strip().lower() for host in os.getenv("AI_PRIVATE_HOST_ALLOWLIST", "").split(",") if host.strip()
    ))
    max_reviews_per_day: int = field(default_factory=lambda: int(os.getenv("MAX_REVIEWS_PER_DAY", "100")))
    max_materials_per_day: int = field(default_factory=lambda: int(os.getenv("MAX_MATERIALS_PER_DAY", "100")))
    start_worker: bool = True
    session_days: int = 7

    @property
    def database_path(self) -> Path:
        return self.data_dir / "learning.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"
