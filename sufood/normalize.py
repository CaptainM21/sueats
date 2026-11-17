"""Turn raw Localist payloads into the EventRow list the dashboard renders.

Two shape problems are handled here:

1. The API returns one top-level entry per *instance*, so a weekly event comes
   back up to 14 times inside a 14-day window. We de-duplicate by event id.
2. Each unique event then carries its own `event_instances` list, which we
   expand back out so every occurrence becomes its own dashboard row -- that
   is what makes "happening today" and date filtering meaningful.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as date_parser

from .config import Config
from .detect import (clean_text, detect_food, detect_registration, is_announcement,
                     is_restricted)
from .models import HIGH, EventRow


def dedupe_events(raw_events: Iterable[dict]) -> list[dict]:
    """Collapse the instance-level API rows down to unique events.

    Each duplicate entry for an event carries only *one* of its occurrences,
    so the instance lists must be merged rather than discarded -- otherwise a
    weekly event keeps just its first date.
    """
    unique: dict[int, dict] = {}
    seen_instances: dict[int, set] = {}

    for event in raw_events:
        event_id = event["id"]
        if event_id not in unique:
            unique[event_id] = dict(event)
            unique[event_id]["event_instances"] = []
            seen_instances[event_id] = set()

        for wrapper in event.get("event_instances") or []:
            instance = wrapper.get("event_instance", wrapper)
            key = instance.get("id") or instance.get("start")
            if key in seen_instances[event_id]:
                continue
            seen_instances[event_id].add(key)
            unique[event_id]["event_instances"].append(wrapper)

    for event in unique.values():
        event["event_instances"].sort(
            key=lambda w: (w.get("event_instance", w) or {}).get("start") or "")

    return list(unique.values())


def _event_types(event: dict) -> list[str]:
    filters = event.get("filters") or {}
    return [item["name"] for item in filters.get("event_types", []) if item.get("name")]


def _department(event: dict) -> str:
    departments = event.get("departments") or []
    if departments:
        return ", ".join(d["name"] for d in departments if d.get("name"))
    return event.get("school_id") and str(event["school_id"]) or ""


def _span_days(event: dict) -> int:
    first, last = event.get("first_date"), event.get("last_date")
    if not first or not last:
        return 0
    try:
        return (date_parser.parse(last).date() - date_parser.parse(first).date()).days
    except (ValueError, TypeError):
        return 0


def _description_text(event: dict) -> str:
    """Prefer the HTML field: Localist's description_text has mojibake."""
    html = event.get("description") or ""
    if html:
        text = clean_text(html)
        if text:
            return text
    return clean_text(event.get("description_text") or "")


def build_rows(raw_events: Iterable[dict], cfg: Config,
               window_days: int | None = None,
               now: datetime | None = None) -> list[EventRow]:
    """Score every unique event, then expand it into one row per occurrence."""
    now = now or datetime.now().astimezone()
    horizon = now + timedelta(days=window_days or cfg.fetch.window_days)
    rows: list[EventRow] = []

    for event in dedupe_events(raw_events):
        description = _description_text(event)
        verdict = detect_food(f"{event['title']}. {description}", cfg.detection)
        if not verdict.found:
            continue

        types = _event_types(event)
        span = _span_days(event)
        registration = detect_registration(
            text=f"{event['title']}. {description}",
            html=event.get("description") or "",
            ticket_url=event.get("ticket_url") or "",
            event_url=event.get("url") or "",
            localist_url=event.get("localist_url") or "",
            cfg=cfg.registration,
        )

        emitted = 0
        for wrapper in event.get("event_instances") or []:
            instance = wrapper.get("event_instance", wrapper)
            try:
                starts_at = date_parser.parse(instance["start"])
            except (KeyError, ValueError, TypeError):
                continue

            all_day = bool(instance.get("all_day"))

            # An application window or deadline is an announcement, not a
            # gathering -- no High food mention redeems it.
            if is_announcement(types, all_day, span,
                               event.get("location_name") or "", cfg.detection):
                continue

            # Exhibitions, all-day items and long-running series only earn a
            # place when the food mention is specific enough to be High.
            if is_restricted(types, all_day, span, cfg.detection) and verdict.confidence != HIGH:
                continue

            if starts_at < now - timedelta(hours=12) or starts_at > horizon:
                continue

            # An all-day run (an application window, a week-long display) is
            # one ongoing thing, not one thing per day -- show it once.
            if all_day and span > cfg.detection.ongoing_span_days and emitted:
                break

            ends_at = None
            if instance.get("end"):
                try:
                    ends_at = date_parser.parse(instance["end"])
                except (ValueError, TypeError):
                    ends_at = None

            rows.append(EventRow(
                event_id=event["id"],
                instance_id=instance.get("id", 0),
                title=clean_text(event["title"]),
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
                location=clean_text(event.get("location_name") or "") or "Location TBA",
                room=clean_text(event.get("room_number") or ""),
                department=_department(event) or "—",
                event_types=types,
                event_url=event.get("localist_url") or "",
                description_text=description,
                description_html=event.get("description") or "",
                photo_url=event.get("photo_url"),
                span_days=span,
                food=verdict,
                registration=registration,
            ))
            emitted += 1

    rows.sort(key=lambda r: r.sort_key)
    return rows
