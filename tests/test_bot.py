from datetime import datetime, timedelta, timezone

import pytest

from app import bot as bot_module
from app import storage
from app.bot import Bot, render_message
from app.filters import reject_reason
from app.storage import Settings

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def listing(id="1", title="1 Main St, Dublin 8", price=1995, beds=2, hours_ago=1, agent="Private"):
    return {"id": id, "title": title, "price": f"€{price} per month", "monthly_price": price, "beds": beds,
            "baths": 1, "published": (NOW - timedelta(hours=hours_ago)).isoformat(), "url": f"https://www.daft.ie/x/{id}",
            "agent": agent, "sections": []}


def test_filters():
    s = Settings(max_price=1800, min_beds=2, exclude_keywords=["share"], exclude_agents=["Bad"], max_age_hours=24)
    assert reject_reason(listing(price=1500), s, NOW) is None
    assert "older" in reject_reason(listing(price=1500, hours_ago=30), s, NOW)
    assert "above" in reject_reason(listing(), s, NOW)
    assert "below" in reject_reason(listing(price=1500, beds=1), s, NOW)
    assert "share" in reject_reason(listing(price=1500, title="House share D8"), s, NOW)
    assert "agent" in reject_reason(listing(price=1500, agent="Bad Lettings"), s, NOW)
    assert reject_reason(listing(price=1500, title="Flat D8"), Settings(include_keywords=["D4"], max_age_hours=None), NOW)


def test_naive_publish_dates_from_daftlistings():
    # daftlistings returns e.g. "2026-11-02 10:00:00" (UTC, no timezone); this used to crash the bot thread.
    s = Settings(max_age_hours=24)
    fresh = {**listing(), "published": "2026-11-02 10:00:00"}
    old = {**listing(), "published": "2026-10-30 10:00:00"}
    assert reject_reason(fresh, s, NOW) is None
    assert "older" in reject_reason(old, s, NOW)


def test_scan_errors_are_reported_not_raised(env, monkeypatch):
    def boom(_):
        raise RuntimeError("daft down")
    monkeypatch.setattr(bot_module.daft_search, "search", boom)
    ok, summary = Bot().scan_once()
    assert not ok and "daft down" in summary
    assert "daft down" in storage.load_state().last_error


def test_render_message_ignores_bad_placeholders():
    assert render_message("{title} {price}", listing()) == "1 Main St, Dublin 8 €1995 per month"
    assert render_message("{nope}", listing()) == "{nope}"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    sent = []
    monkeypatch.setattr(bot_module.telegram, "send", lambda token, chat, text, html=True: sent.append(text))
    monkeypatch.setattr(bot_module.time, "sleep", lambda _: None)
    results = {"items": []}
    monkeypatch.setattr(bot_module.daft_search, "search", lambda s: list(results["items"]))
    storage.save_settings(Settings(max_age_hours=None, max_notifications_per_run=2, telegram_token="t", telegram_chat_id="c"))
    return sent, results


def test_remember_then_only_new_listings_are_sent(env):
    sent, results = env
    b = Bot()
    results["items"] = [listing("1"), listing("2"), listing("3")]
    assert b.remember_current() == 3
    b.scan_once()
    assert sent == []

    results["items"] = [listing("4"), listing("1"), listing("2"), listing("3")]
    b.scan_once()
    assert len(sent) == 2, "copy text, then details"
    assert sent[0].startswith("Hi, I'm interested in 1 Main St") and "x/4" in sent[1]
    b.scan_once()
    assert len(sent) == 2, "a listing is only sent once"


def test_cap_defers_rest_to_next_run(env):
    sent, results = env
    b = Bot()
    results["items"] = [listing(str(i)) for i in range(5)]
    b.scan_once()
    assert len(sent) == 4
    b.scan_once()
    assert len(sent) == 8
    assert len(storage.load_state().seen) == 4


def test_loop_schedules_next_run(env, monkeypatch):
    b = Bot()
    storage.save_settings(Settings(running=True, max_age_hours=None))

    class StopLoop(Exception):
        pass

    def stop_waiting(timeout):
        raise StopLoop
    monkeypatch.setattr(b._wake, "wait", stop_waiting)
    with pytest.raises(StopLoop):
        b._loop()
    state = storage.load_state()
    assert state.last_run_at and state.next_run_at
    assert not any("loop error" in e["message"] for e in state.events)
