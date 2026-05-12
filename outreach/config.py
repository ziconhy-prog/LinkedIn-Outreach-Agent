"""Configuration loader. Reads from .env, falls back to sensible defaults."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = parent of the outreach/ package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root if present. Missing file is fine.
load_dotenv(PROJECT_ROOT / ".env")


def _path(env_var: str, default: Path) -> Path:
    """Resolve a path from an env var, falling back to ``default``.

    Relative paths are resolved against the project root.
    """
    raw = os.getenv(env_var, "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        return candidate.resolve()
    return default.resolve()


# Filesystem paths
DATA_DIR: Path = _path("DATA_DIR", PROJECT_ROOT / "data")
LOGS_DIR: Path = _path("LOGS_DIR", PROJECT_ROOT / "logs")
DB_PATH: Path = _path("DB_PATH", DATA_DIR / "outreach.db")
VOICE_SAMPLES_DIR: Path = _path(
    "VOICE_SAMPLES_DIR", PROJECT_ROOT / "files" / "voice-samples"
)
PLAYWRIGHT_USER_DATA_DIR: Path = _path(
    "PLAYWRIGHT_USER_DATA_DIR", PROJECT_ROOT / ".playwright-session"
)

# Telegram (Phase 4+) — empty in Phase 1.
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_OPERATOR_USER_ID: str = os.getenv("TELEGRAM_OPERATOR_USER_ID", "").strip()


def ensure_dirs() -> None:
    """Create data/ and logs/ directories if they don't yet exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
