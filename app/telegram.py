"""Minimal Telegram Bot API client."""

from __future__ import annotations

import html

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


def _call(token: str, method: str, **payload) -> dict:
    if not token:
        raise TelegramError("Telegram bot token is not set.")
    r = requests.post(API.format(token=token, method=method), json=payload, timeout=20)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok"):
        raise TelegramError(data.get("description") or f"HTTP {r.status_code}")
    return data["result"]


def send(token: str, chat_id: str, text: str, html: bool = True) -> None:
    if not chat_id:
        raise TelegramError("Telegram chat id is not set.")
    payload = {"chat_id": chat_id, "text": text}
    if html:
        payload["parse_mode"] = "HTML"
    _call(token, "sendMessage", **payload)


def recent_chats(token: str) -> list[dict]:
    """Chats that recently messaged the bot, so the admin page can offer the chat id."""
    chats = {}
    for update in _call(token, "getUpdates"):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username")
            chats[str(chat["id"])] = {"id": str(chat["id"]), "name": name}
    return list(chats.values())


def format_listing(listing: dict) -> str:
    e = html.escape
    details = " · ".join(filter(None, [
        e(listing["price"]),
        f"{listing['beds']} bed" if listing.get("beds") else None,
        f"{listing['baths']} bath" if listing.get("baths") else None,
    ]))
    lines = [
        "🏠 <b>New rental on Daft</b>",
        f"<b>{e(listing['title'])}</b>",
        details,
    ]
    if listing.get("agent"):
        lines.append(f"Agent: {e(listing['agent'])}")
    lines.append(f'<a href="{e(listing["url"])}">Open on daft.ie</a>')
    return "\n".join(lines)
