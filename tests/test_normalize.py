"""Pipeline tests: de-duplication, instance expansion, and the ongoing-event rule."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from dateutil import parser as date_parser

from sufood.config import load_config
from sufood.detect import clean_text, detect_food
from sufood.models import HIGH
from sufood.normalize import build_rows, dedupe_events

FIXTURE = Path(__file__).parent / "fixtures" / "api_events_raw.json"
TEST_EVENT_SLUG = "food-for-thought-say-goodbye-to-silos-building-connections-across-su"

# The fixture was captured on this date; pin "now" so the window is stable.
CAPTURED_AT = date_parser.parse("2026-11-16T08:00:00-05:00")


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def raw_events():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows(raw_events, cfg):
    return build_rows(raw_events, cfg, now=CAPTURED_AT)


def make_event(event_id=90001, title="Synthetic Event", description="Lunch will be provided.",
               start="2026-11-17T00:00:00-05:00", span_days=10, all_day=True,
               location="Hendricks Chapel", event_types=("Social Activities",)):
    """A minimal Localist-shaped event, for rules the live fixture can't exercise."""
    first = date_parser.parse(start).date()
    last = first + timedelta(days=span_days)
    instances = [{
        "event_instance": {
            "id": event_id * 10 + n,
            "start": (date_parser.parse(start) + timedelta(days=n)).isoformat(),
            "all_day": all_day,
        }
    } for n in range(span_days + 1)]
    return {
        "id": event_id,
        "title": title,
        "description": f"<p>{description}</p>",
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "location_name": location,
        "filters": {"event_types": [{"name": n} for n in event_types]},
        "departments": [{"name": "Test Department"}],
        "localist_url": f"https://events.syracuse.edu/event/{event_id}",
        "event_instances": instances,
    }


def test_dedupe_collapses_instance_level_rows(raw_events):
    """The API returns one entry per occurrence; 488 of them are 178 events."""
    assert len(raw_events) == 488
    assert len(dedupe_events(raw_events)) == 178


def test_recurring_event_expands_to_one_row_per_occurrence(rows):
    """A weekly food event should appear once per date in the window."""
    counts = {}
    for row in rows:
        counts.setdefault(row.event_id, []).append(row)
    repeats = [v for v in counts.values() if len(v) > 1]
    assert repeats, "expected at least one recurring food event in the window"

    for group in repeats:
        verdicts = {r.food.confidence for r in group}
        assert len(verdicts) == 1, "occurrences of one event must share a verdict"
        starts = [r.starts_at for r in group]
        assert len(set(starts)) == len(starts), "occurrences must have distinct times"


def test_rows_are_sorted_soonest_first(rows):
    assert rows == sorted(rows, key=lambda r: r.sort_key)
    assert [r.starts_at for r in rows] == sorted(r.starts_at for r in rows)


def test_test_event_present_with_evidence(rows):
    """End-to-end: the named acceptance event survives the whole pipeline."""
    matches = [r for r in rows if TEST_EVENT_SLUG in r.event_url]
    assert matches, "the Food for Thought event must reach the dashboard"
    row = matches[0]
    assert row.food.confidence == HIGH
    assert "light lunch" in " ".join(m.phrase.lower() for m in row.food.matches)
    assert "light lunch" in row.food.best_match.sentence.lower()
    assert row.location == "Bird Library"
    assert row.room == "114"
    assert row.department == "Office of People and Culture"


def test_turkeys_for_veterans_never_reaches_high(rows, raw_events):
    for row in rows:
        if "turkeys for veterans" in row.title.lower():
            assert row.food.confidence != HIGH


def test_club_sports_are_excluded_entirely(rows):
    """Restricted categories need High confidence, which they never reach."""
    for row in rows:
        assert "Club and Intramural Sports" not in row.event_types or row.food.confidence == HIGH


def test_exhibitions_require_high_confidence(rows):
    for row in rows:
        if "Exhibitions" in row.event_types:
            assert row.food.confidence == HIGH, f"{row.title} is a low-confidence exhibition"


def test_ongoing_all_day_runs_require_high_confidence(cfg):
    """Multi-day all-day runs are 'ongoing' and need a specific food mention.

    Built from a synthetic event rather than the fixture: once announcement
    listings are excluded, the live window contains no all-day food rows at
    all, so a loop over `rows` would pass while testing nothing.
    """
    weak = make_event(event_id=90010, description="Lunch options are nearby.")
    assert build_rows([weak], cfg, now=CAPTURED_AT) == []

    strong = make_event(event_id=90011, description="Lunch will be provided.")
    strong_rows = build_rows([strong], cfg, now=CAPTURED_AT)
    assert strong_rows and strong_rows[0].food.confidence == HIGH


def test_recurring_timed_events_are_not_treated_as_ongoing(rows):
    """A weekly 6pm meeting repeats; it is not an ongoing multi-day item."""
    recurring_timed = [r for r in rows if not r.all_day and r.span_days > 7]
    assert recurring_timed, "fixture should contain recurring timed food events"
    assert any(r.food.confidence != HIGH for r in recurring_timed), \
        "recurring timed events should be judged at their own confidence"


def test_rows_stay_inside_the_window(rows, cfg):
    for row in rows:
        delta = row.starts_at - CAPTURED_AT
        assert delta.days <= cfg.fetch.window_days
        assert delta.total_seconds() > -12 * 3600


def test_window_days_is_configurable(raw_events, cfg):
    short = build_rows(raw_events, cfg, window_days=2, now=CAPTURED_AT)
    long = build_rows(raw_events, cfg, window_days=14, now=CAPTURED_AT)
    assert len(short) < len(long)


def test_every_row_carries_displayable_evidence(rows):
    for row in rows:
        best = row.food.best_match
        assert best is not None
        assert best.phrase.strip()
        assert best.sentence.strip()


def test_descriptions_are_free_of_mojibake(rows):
    """Localist's description_text contains U+FFFD; we parse the HTML instead."""
    for row in rows:
        assert "�" not in row.description_text
        assert "<" not in row.description_text
        assert "&amp;" not in row.description_text


def test_ongoing_all_day_runs_appear_once(cfg):
    """A week-long all-day item is one ongoing thing, not one row per day."""
    event = make_event(event_id=90012, span_days=10)
    assert len(event["event_instances"]) == 11
    rows = build_rows([event], cfg, now=CAPTURED_AT)
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Announcement listings: application windows, deadlines, nomination periods.
# ---------------------------------------------------------------------------

ANNOUNCEMENT_TITLE = "2027 Orientation Leader Applications"


def test_application_windows_never_appear(rows, raw_events, cfg):
    """The row is gone because of what it *is*, not what it says.

    Its text genuinely promises food -- "meals provided during summer training"
    -- and detect_food still grades that High in isolation. It is excluded
    because an all-day run with no event type and no venue is an announcement,
    not a gathering anyone can eat at.
    """
    source = next(e for e in raw_events if e["title"] == ANNOUNCEMENT_TITLE)
    text = f"{source['title']}. {clean_text(source['description'])}"
    assert detect_food(text, cfg.detection).confidence == HIGH

    assert not [r for r in rows if r.title == ANNOUNCEMENT_TITLE]


def test_no_venueless_all_day_announcement_survives(rows):
    for row in rows:
        if row.all_day and row.span_days > 7:
            assert row.event_types and row.location != "Location TBA", row.title


def test_announcement_rule_is_configurable(raw_events):
    """The config toggle is real, not decorative."""
    relaxed = load_config()
    relaxed.detection.exclude_announcements = False
    titles = {r.title for r in build_rows(raw_events, relaxed, now=CAPTURED_AT)}
    assert ANNOUNCEMENT_TITLE in titles


def test_multi_day_event_with_a_venue_still_qualifies(cfg):
    """The anti-goal: a real multi-day event must not be caught by the rule."""
    event = make_event(event_id=90020, title="Weeklong Food Festival",
                       location="Quad", event_types=("Social Activities",))
    rows = build_rows([event], cfg, now=CAPTURED_AT)
    assert len(rows) == 1
    assert rows[0].food.confidence == HIGH


def test_salaam_shalom_is_high_on_its_scheduled_dinner(rows):
    """"Each session begins with dinner from 6:30 to 7 pm" is a real meal."""
    matches = [r for r in rows if "salaam shalom" in r.title.lower()]
    assert matches, "the Salaam Shalom sessions must reach the dashboard"
    row = matches[0]
    assert row.food.confidence == HIGH
    assert "dinner" in row.food.best_match.sentence.lower()
