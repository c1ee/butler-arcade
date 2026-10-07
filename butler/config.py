"""Settings from `.env` (real environment variables win) plus system constants."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# System-only: every Dinner time is read and written in this zone. Butler never asks.
TIMEZONE = "America/Los_Angeles"
DEFAULT_POLL_SECONDS = 30
DEFAULT_MODEL = "claude-sonnet-5-5"

# One consent covers every catalog tool Butler calls (ticket 05).
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/" + scope
    for scope in ["gmail.send", "gmail.readonly", "calendar.events", "calendar.readonly", "calendar.settings.readonly"]
]

REQUIRED = ["ARCADE_API_KEY", "ANTHROPIC_API_KEY", "BUTLER_USER_ID", "HOST_EMAIL"]


@dataclass(frozen=True)
class Settings:
    arcade_api_key: str
    anthropic_api_key: str
    butler_user_id: str  # Butler's Gmail address, also its Arcade user id (D1)
    host_email: str
    model: str = DEFAULT_MODEL
    poll_seconds: int = DEFAULT_POLL_SECONDS
    db_path: Path = ROOT / "butler.db"

    @property
    def butler_email(self) -> str:
        return self.butler_user_id.lower()


def read_env_file(path: Path = ROOT / ".env") -> None:
    """Copy `.env` into the environment; variables already set win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def load() -> Settings:
    read_env_file()
    missing = [key for key in REQUIRED if not os.environ.get(key)]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in.")
    return Settings(
        arcade_api_key=os.environ["ARCADE_API_KEY"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        butler_user_id=os.environ["BUTLER_USER_ID"],
        host_email=os.environ["HOST_EMAIL"].lower(),
        model=os.environ.get("MODEL") or DEFAULT_MODEL,
        poll_seconds=int(os.environ.get("POLL_SECONDS") or DEFAULT_POLL_SECONDS),
    )
