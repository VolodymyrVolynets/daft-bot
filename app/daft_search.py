"""Searches daft.ie rentals through the daftlistings library and turns results into plain dicts."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from daftlistings import AddedSince, Daft, Location, PropertyType, SearchType, SortType

from .storage import Settings

RENTAL_PROPERTY_TYPES = [
    "APARTMENT", "STUDIO_APARTMENT", "HOUSE", "DETACHED_HOUSE", "SEMI_DETACHED_HOUSE",
    "TERRACED_HOUSE", "END_OF_TERRACE_HOUSE", "TOWNHOUSE", "DUPLEX", "BUNGALOW",
]


def location_names() -> list[str]:
    return [loc.name for loc in Location]


def is_known_location(name: str) -> bool:
    return name in Location.__members__


def search(settings: Settings) -> list[dict]:
    """Newest listings first. One request per property type, because daft accepts only one type per search."""
    locations = [Location[n] for n in settings.locations if is_known_location(n)]
    if not locations:
        raise ValueError("No valid locations configured.")

    results: dict[str, dict] = {}
    for property_type in settings.property_types or [None]:
        daft = Daft()
        daft.set_search_type(SearchType.RESIDENTIAL_RENT)
        daft.set_sort_type(SortType.PUBLISH_DATE_DESC)
        daft.set_location(locations)
        if settings.min_price:
            daft.set_min_price(settings.min_price)
        if settings.max_price:
            daft.set_max_price(settings.max_price)
        if settings.min_beds:
            daft.set_min_beds(settings.min_beds)
        if settings.max_beds:
            daft.set_max_beds(settings.max_beds)
        if property_type:
            daft.set_property_type(PropertyType[property_type])
        if settings.max_age_hours and settings.max_age_hours <= 72:
            daft.set_added_since(AddedSince.DAYS_3)

        for listing in daft.search(max_pages=max(1, settings.max_pages)):
            item = to_dict(listing)
            if item["id"]:
                results.setdefault(item["id"], item)

    return sorted(results.values(), key=lambda x: x["published"] or "", reverse=True)


def _safe(listing, attr: str):
    # daftlistings reads straight from the API JSON, so a missing field raises instead of returning None.
    try:
        return getattr(listing, attr)
    except Exception:
        return None


def _first_int(text) -> int | None:
    if text is None:
        return None
    if isinstance(text, int):
        return text
    m = re.search(r"\d+", str(text))
    return int(m.group()) if m else None


def parse_utc(value) -> datetime | None:
    """daftlistings gives publish dates as naive UTC strings ("2026-10-01 10:50:03"); make them timezone-aware."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def to_dict(listing) -> dict:
    published = parse_utc(_safe(listing, "publish_date"))
    published = published.isoformat(timespec="seconds") if published else None
    link = _safe(listing, "daft_link") or ""
    return {
        "id": str(_safe(listing, "id") or ""),
        "title": _safe(listing, "title") or "(untitled)",
        "price": _safe(listing, "price") or "",
        "monthly_price": _first_int(_safe(listing, "monthly_price")),
        "beds": _first_int(_safe(listing, "bedrooms")),
        "baths": _first_int(_safe(listing, "bathrooms")),
        "published": published,
        "url": link.replace("http://", "https://", 1),
        "agent": (_safe(listing, "agent_name") or "").strip(),
        "sections": _safe(listing, "sections") or [],
    }
