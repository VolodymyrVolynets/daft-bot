"""Admin web page: edit criteria, start/stop the bot, remember current listings, view matches and the log."""

from __future__ import annotations

import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import daft_search, telegram
from .bot import Bot
from .storage import load_settings, load_state, save_settings

BASE = Path(__file__).parent
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

bot = Bot()


@asynccontextmanager
async def lifespan(_: FastAPI):
    bot.start_thread()
    yield


app = FastAPI(title="Daft rental bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
security = HTTPBasic(auto_error=False)


def require_login(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    """HTTP Basic auth with any username and ADMIN_PASSWORD; open when no password is configured."""
    if not ADMIN_PASSWORD:
        return
    if credentials is None or not secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": 'Basic realm="daft-bot"'})


def back(path: str, msg: str, kind: str = "ok") -> RedirectResponse:
    return RedirectResponse(f"{path}?msg={quote(msg)}&kind={kind}", status_code=303)


def split_list(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[\n,]", text or "") if x.strip()]


def to_int(text: str) -> int | None:
    text = (text or "").strip()
    return int(text) if text.isdigit() else None


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", dependencies=[Depends(require_login)])
def dashboard(request: Request, msg: str = "", kind: str = "ok"):
    return templates.TemplateResponse(request, "index.html", {
        "state": load_state(), "settings": load_settings(), "msg": msg, "kind": kind,
        "auth_enabled": bool(ADMIN_PASSWORD),
    })


@app.post("/start", dependencies=[Depends(require_login)])
def start(remember: str = Form("")):
    note = ""
    if remember:
        try:
            note = f" Remembered {bot.remember_current()} current listings first."
        except Exception as exc:
            return back("/", f"Could not remember current listings, bot not started: {exc}", "error")
    bot.start()
    return back("/", "Bot started." + note)


@app.post("/stop", dependencies=[Depends(require_login)])
def stop():
    bot.stop()
    return back("/", "Bot stopped.")


@app.post("/run-now", dependencies=[Depends(require_login)])
def run_now():
    # Runs in this request (a few seconds) so the result shows straight away; works while stopped too.
    ok, summary = bot.scan_once()
    return back("/", f"Scan finished: {summary}" if ok else summary, "ok" if ok else "error")


@app.post("/remember", dependencies=[Depends(require_login)])
def remember():
    try:
        return back("/", f"Remembered {bot.remember_current()} current listings. Only newer ones will be notified.")
    except Exception as exc:
        return back("/", f"Search failed: {exc}", "error")


@app.post("/forget", dependencies=[Depends(require_login)])
def forget():
    bot.forget_all()
    return back("/", "Forgot all remembered listings. The next scan may send many messages.", "warn")


@app.get("/settings", dependencies=[Depends(require_login)])
def settings_page(request: Request, msg: str = "", kind: str = "ok"):
    return templates.TemplateResponse(request, "settings.html", {
        "s": load_settings(), "msg": msg, "kind": kind,
        "all_locations": daft_search.location_names(),
        "property_types": daft_search.RENTAL_PROPERTY_TYPES,
        "env_token": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "env_chat": bool(os.environ.get("TELEGRAM_CHAT_ID")),
    })


@app.post("/settings", dependencies=[Depends(require_login)])
def save_settings_form(
    locations: str = Form(""), property_types: list[str] = Form([]),
    min_price: str = Form(""), max_price: str = Form(""), min_beds: str = Form(""), max_beds: str = Form(""),
    max_pages: str = Form("2"), include_keywords: str = Form(""), exclude_keywords: str = Form(""),
    exclude_agents: str = Form(""), max_age_hours: str = Form(""), interval_minutes: str = Form("10"),
    max_notifications_per_run: str = Form("10"), message_template: str = Form(""),
    telegram_token: str = Form(""), telegram_chat_id: str = Form(""), remember_after: str = Form(""),
):
    names = [n.upper().replace(" ", "_") for n in split_list(locations)]
    unknown = [n for n in names if not daft_search.is_known_location(n)]
    if unknown or not names:
        return back("/settings", f"Unknown location(s): {', '.join(unknown) or 'none given'}. Pick from the suggestions.", "error")

    s = load_settings()
    s.locations = names
    s.property_types = [p for p in property_types if p in daft_search.RENTAL_PROPERTY_TYPES]
    s.min_price, s.max_price = to_int(min_price), to_int(max_price)
    s.min_beds, s.max_beds = to_int(min_beds), to_int(max_beds)
    s.max_pages = min(max(to_int(max_pages) or 1, 1), 10)
    s.include_keywords, s.exclude_keywords = split_list(include_keywords), split_list(exclude_keywords)
    s.exclude_agents = split_list(exclude_agents)
    s.max_age_hours = to_int(max_age_hours)
    s.interval_minutes = max(to_int(interval_minutes) or 10, 5)
    s.max_notifications_per_run = max(to_int(max_notifications_per_run) or 10, 1)
    s.message_template = message_template.strip()
    # Blank token field = keep the current one (the page never shows it).
    if telegram_token.strip():
        s.telegram_token = telegram_token.strip()
    s.telegram_chat_id = telegram_chat_id.strip()
    save_settings(s)

    if remember_after:
        try:
            return back("/settings", f"Saved. Remembered {bot.remember_current()} listings matching the new criteria.")
        except Exception as exc:
            return back("/settings", f"Saved, but remembering current listings failed: {exc}", "error")
    return back("/settings", "Saved.")


@app.post("/telegram/clear-token", dependencies=[Depends(require_login)])
def clear_token():
    s = load_settings()
    s.telegram_token = ""
    save_settings(s)
    return back("/settings", "Telegram token removed.")


@app.post("/telegram/test", dependencies=[Depends(require_login)])
def telegram_test():
    s = load_settings()
    try:
        telegram.send(s.effective_telegram_token, s.effective_telegram_chat_id, "✅ Daft bot test message: notifications work.")
        return back("/settings", "Test message sent. Check Telegram.")
    except Exception as exc:
        return back("/settings", f"Telegram error: {exc}", "error")


@app.post("/telegram/detect", dependencies=[Depends(require_login)])
def telegram_detect():
    s = load_settings()
    try:
        chats = telegram.recent_chats(s.effective_telegram_token)
    except Exception as exc:
        return back("/settings", f"Telegram error: {exc}", "error")
    if not chats:
        return back("/settings", "No chats found. Send any message to your bot in Telegram, then try again.", "warn")
    if len(chats) == 1:
        s.telegram_chat_id = chats[0]["id"]
        save_settings(s)
        return back("/settings", f"Chat id set to {chats[0]['id']} ({chats[0]['name']}).")
    found = "; ".join(f"{c['id']} ({c['name']})" for c in chats)
    return back("/settings", f"Several chats found, paste the right id: {found}", "warn")
