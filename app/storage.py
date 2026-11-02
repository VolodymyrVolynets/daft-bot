"""Settings and bot state, kept as JSON files in the data directory (a Docker volume)."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MAX_SEEN = 10_000
MAX_EVENTS = 300
MAX_MATCHES = 200

_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Settings:
    # Search (sent to daft.ie)
    locations: list[str] = field(default_factory=lambda: ["DUBLIN_CITY"])
    property_types: list[str] = field(default_factory=list)
    min_price: int | None = None
    max_price: int | None = 2500
    min_beds: int | None = 1
    max_beds: int | None = None
    max_pages: int = 2

    # Extra filters (checked by the bot)
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=lambda: ["house share", "room to rent", "student"])
    exclude_agents: list[str] = field(default_factory=list)
    max_age_hours: int | None = 48

    # Bot behaviour
    interval_minutes: int = 10
    max_notifications_per_run: int = 10
    message_template: str = (
        "Hi, I'm interested in {title} ({price}) and would love to arrange a viewing. "
        "I'm a working professional, non-smoker, with references available. Thanks!"
    )

    # Telegram (environment variables TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are used when these are empty)
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @property
    def effective_telegram_token(self) -> str:
        return self.telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")

    @property
    def effective_telegram_chat_id(self) -> str:
        return self.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")


@dataclass
class State:
    running: bool = False
    # Listing id -> when it was remembered. Remembered listings never trigger a notification.
    seen: dict[str, str] = field(default_factory=dict)
    remembered_at: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_run_summary: str | None = None
    last_error: str | None = None
    matches: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


def _read(name: str, cls):
    path = DATA_DIR / name
    if not path.exists():
        return cls()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in known})


def _write(name: str, obj) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(obj), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_settings() -> Settings:
    with _lock:
        return _read("settings.json", Settings)


def save_settings(settings: Settings) -> None:
    with _lock:
        _write("settings.json", settings)


def load_state() -> State:
    with _lock:
        return _read("state.json", State)


def save_state(state: State) -> None:
    with _lock:
        if len(state.seen) > MAX_SEEN:
            newest = sorted(state.seen.items(), key=lambda kv: kv[1], reverse=True)[:MAX_SEEN]
            state.seen = dict(newest)
        state.events = state.events[:MAX_EVENTS]
        state.matches = state.matches[:MAX_MATCHES]
        _write("state.json", state)


def update_state(fn) -> State:
    """Load, modify and save the state under one lock so the bot thread and the web page don't overwrite each other."""
    with _lock:
        state = load_state()
        fn(state)
        save_state(state)
        return state


def log_event(state: State, level: str, message: str) -> None:
    print(f"[{level}] {message}", flush=True)
    state.events.insert(0, {"at": now_iso(), "level": level, "message": message})
