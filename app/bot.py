"""The scanning loop: search daft, skip remembered listings, filter, notify via Telegram."""

from __future__ import annotations

import random
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import daft_search, telegram
from .filters import reject_reason
from .storage import Settings, load_settings, load_state, log_event, now_iso, update_state


def render_message(template: str, listing: dict) -> str:
    try:
        return template.format(**{k: ("" if v is None else v) for k, v in listing.items()})
    except (KeyError, IndexError, ValueError):
        return template


class Bot:
    def __init__(self) -> None:
        self._wake = threading.Event()
        self._run_lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="daft-bot", daemon=True)

    def start_thread(self) -> None:
        self._thread.start()

    # ---- controls used by the admin page -------------------------------------------------

    def start(self) -> None:
        update_state(lambda s: (setattr(s, "running", True), log_event(s, "info", "Bot started")))
        self._wake.set()

    def stop(self) -> None:
        update_state(lambda s: (setattr(s, "running", False), log_event(s, "info", "Bot stopped")))

    def remember_current(self) -> int:
        """Mark every listing that currently matches the search as already seen, without notifying."""
        with self._run_lock:
            settings = load_settings()
            listings = daft_search.search(settings)
            stamp = now_iso()

            def apply(state):
                for listing in listings:
                    state.seen.setdefault(listing["id"], stamp)
                state.remembered_at = stamp
                log_event(state, "info", f"Remembered {len(listings)} current listings; they won't be notified")

            update_state(apply)
            return len(listings)

    def forget_all(self) -> None:
        def apply(state):
            state.seen.clear()
            state.remembered_at = None
            log_event(state, "warn", "Forgot all remembered listings")
        update_state(apply)

    # ---- loop ------------------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            # Nothing may escape this loop: an uncaught error would end the thread and silently stop the timer.
            delay = 600
            try:
                settings = load_settings()
                delay = max(5, settings.interval_minutes) * 60 + random.randint(0, 45)  # jitter
                if load_state().running:
                    self.scan_once(settings)
                running = load_state().running
                next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")
                update_state(lambda s: setattr(s, "next_run_at", next_at if running else None))
            except Exception as exc:
                traceback.print_exc()
                try:
                    update_state(lambda s: log_event(s, "error", f"Bot loop error: {exc}"))
                except Exception:
                    pass
            self._wake.wait(timeout=delay)
            self._wake.clear()

    def scan_once(self, settings: Settings | None = None) -> tuple[bool, str]:
        """One scan. Returns (ok, summary); errors are recorded in the state instead of raised."""
        with self._run_lock:
            settings = settings or load_settings()
            try:
                return self._scan(settings)
            except Exception as exc:  # network errors, daft blocking, library changes, bugs
                traceback.print_exc()
                msg = f"Scan failed: {exc}"
                update_state(lambda s: (setattr(s, "last_error", msg), setattr(s, "last_run_at", now_iso()), log_event(s, "error", msg)))
                return False, msg

    def _scan(self, settings: Settings) -> tuple[bool, str]:
        listings = daft_search.search(settings)
        now = datetime.now(timezone.utc)
        state = update_state(lambda s: None)
        new = [l for l in listings if l["id"] not in state.seen]
        matched, notified, errors = [], 0, []

        for listing in new:
            if reject_reason(listing, settings, now) is None:
                matched.append(listing)

        # Listings past the cap are left unremembered, so they're sent on the next run instead of being lost.
        to_send = matched[: max(1, settings.max_notifications_per_run)]
        sent_ids: list[str] = []
        for listing in to_send:
            message = render_message(settings.message_template, listing)
            try:
                token, chat = settings.effective_telegram_token, settings.effective_telegram_chat_id
                # Two messages: the enquiry text on its own (plain, so it copies cleanly), then the listing details.
                if message.strip():
                    telegram.send(token, chat, message, html=False)
                telegram.send(token, chat, telegram.format_listing(listing))
                notified += 1
                sent_ids.append(listing["id"])
                time.sleep(1)  # stay well inside Telegram's rate limit
            except Exception as exc:
                errors.append(str(exc))
                break  # Telegram is down or misconfigured: retry these next run

        summary = (f"{len(listings)} listings, {len(new)} not remembered, {len(matched)} matched, "
                   f"{notified} notified" + (f", {len(matched) - notified} waiting" if len(matched) > notified else ""))

        def apply(s):
            stamp = now_iso()
            for listing in to_send:
                if listing["id"] in sent_ids:
                    s.seen[listing["id"]] = stamp
                    s.matches.insert(0, {**listing, "notified_at": stamp})
            s.last_run_at = stamp
            s.last_run_summary = summary
            s.last_error = errors[0] if errors else None
            log_event(s, "error" if errors else "info", summary + (f" — Telegram: {errors[0]}" if errors else ""))

        update_state(apply)
        return not errors, summary
