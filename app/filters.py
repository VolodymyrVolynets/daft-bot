"""Criteria daft's search can't express (keywords, agents, listing age), plus a re-check of price and beds."""

from __future__ import annotations

from datetime import datetime, timedelta

from .daft_search import parse_utc
from .storage import Settings


def _contains(text: str, word: str) -> bool:
    return bool(word.strip()) and word.strip().lower() in (text or "").lower()


def reject_reason(listing: dict, s: Settings, now: datetime) -> str | None:
    """None when the listing matches, otherwise why it doesn't."""
    published = parse_utc(listing.get("published"))
    if s.max_age_hours and published:
        if now - published > timedelta(hours=s.max_age_hours):
            return f"older than {s.max_age_hours}h"

    price = listing.get("monthly_price")
    if price is not None and s.min_price and price < s.min_price:
        return f"price {price} below {s.min_price}"
    if price is not None and s.max_price and price > s.max_price:
        return f"price {price} above {s.max_price}"

    beds = listing.get("beds")
    if beds is not None and s.min_beds and beds < s.min_beds:
        return f"{beds} beds below {s.min_beds}"
    if beds is not None and s.max_beds and beds > s.max_beds:
        return f"{beds} beds above {s.max_beds}"

    title = listing.get("title", "")
    for word in s.exclude_keywords:
        if _contains(title, word):
            return f'title contains "{word}"'
    if s.include_keywords and not any(_contains(title, w) for w in s.include_keywords):
        return "title has none of the include keywords"

    for agent in s.exclude_agents:
        if _contains(listing.get("agent", ""), agent):
            return f'agent "{agent}" excluded'

    return None
