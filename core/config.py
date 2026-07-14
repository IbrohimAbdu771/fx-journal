"""Configuration loaded from environment (.env)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

LOG_FILE = BASE_DIR / "journal.log"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val or ""


def _normalize_db_url(url: str) -> tuple[str, bool]:
    """Make any DATABASE_URL async-driver friendly. Returns (url, ssl_required).

    Railway/Heroku/Neon hand out `postgres://…` or `postgresql://…`; SQLAlchemy
    async needs `postgresql+asyncpg://…`. asyncpg also does NOT understand the
    libpq query params `sslmode` / `channel_binding`, so we strip them and signal
    SSL separately via connect_args. Local default is a bundled SQLite file.
    """
    if not url:
        return f"sqlite+aiosqlite:///{BASE_DIR / 'journal.db'}", False

    ssl_required = ("sslmode=require" in url or "sslmode=verify" in url
                    or any(h in url for h in ("neon.tech", "amazonaws.com", "render.com")))

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("sqlite:///"):
        url = "sqlite+aiosqlite:///" + url[len("sqlite:///"):]

    # drop asyncpg-incompatible libpq params
    if "?" in url:
        base, _, query = url.partition("?")
        keep = [
            p for p in query.split("&")
            if p and p.split("=")[0] not in {"sslmode", "channel_binding"}
        ]
        url = base + ("?" + "&".join(keep) if keep else "")
    return url, ssl_required


@dataclass(frozen=True)
class Config:
    # storage
    database_url: str
    db_ssl: bool
    # telegram bot
    telegram_bot_token: str
    allowed_user_id: int
    bot_enabled: bool
    # claude / speech
    anthropic_api_key: str
    yandex_speechkit_api_key: str
    yandex_stt_lang: str
    claude_model: str
    # web
    web_password: str        # empty = no auth gate
    # account / locale
    initial_balance: float
    timezone: str


def load_config() -> Config:
    allowed_raw = _get("ALLOWED_TELEGRAM_USER_ID")
    allowed_user_id = int(allowed_raw) if allowed_raw.strip().lstrip("-").isdigit() else 0

    telegram_token = _get("TELEGRAM_BOT_TOKEN")
    # The bot is optional: the web dashboard runs fine on its own.
    bot_enabled = bool(telegram_token and allowed_user_id and _get("ANTHROPIC_API_KEY"))

    balance_raw = _get("INITIAL_BALANCE", "0")
    try:
        initial_balance = float(balance_raw)
    except ValueError:
        initial_balance = 0.0

    db_url, db_ssl = _normalize_db_url(_get("DATABASE_URL"))
    return Config(
        database_url=db_url,
        db_ssl=db_ssl,
        telegram_bot_token=telegram_token,
        allowed_user_id=allowed_user_id,
        bot_enabled=bot_enabled,
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        yandex_speechkit_api_key=_get("YANDEX_SPEECHKIT_API_KEY"),
        yandex_stt_lang=_get("YANDEX_STT_LANG", "ru-RU"),
        claude_model=_get("CLAUDE_MODEL", "claude-sonnet-5"),
        web_password=_get("WEB_PASSWORD"),
        initial_balance=initial_balance,
        timezone=_get("TRADER_TIMEZONE", "America/New_York"),
    )
