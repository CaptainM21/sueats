"""Data structures shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

HIGH, MEDIUM, LOW = "High", "Medium", "Low"
CONFIDENCE_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}

# How an occurrence sits against the clock right now.
LIVE, SOON, UPCOMING, PAST = "live", "soon", "upcoming", "past"

SOON_MINUTES = 90          # "starts in ..." is only useful inside this window
ASSUMED_LENGTH = timedelta(hours=1)   # when Localist gives no end time


def _comparable(moment: datetime, now: datetime) -> tuple[datetime, datetime]:
    """Make two datetimes safe to compare.

    Localist timestamps are timezone-aware (dateutil keeps the offset), so a
    caller passing a naive `datetime.now()` would raise TypeError. Rather than
    invent a zone, drop both sides to wall time -- the events and the student
    reading them are in the same place.
    """
    if (moment.tzinfo is None) != (now.tzinfo is None):
        return moment.replace(tzinfo=None), now.replace(tzinfo=None)
    return moment, now


def humanize(delta: timedelta) -> str:
    """'24 min', '1 hr 10 min', '6 hr' -- never '0 hr 7 min'."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 6 and rest:
        return f"{hours} hr {rest} min"
    return f"{hours} hr"


@dataclass(frozen=True)
class FoodMatch:
    """One keyword hit, kept with enough context for a human to judge it."""

    phrase: str          # the literal text that matched, e.g. "light lunch"
    sentence: str        # the full sentence it appeared in
    strength: str        # "strong" or "weak"
    start: int           # char offset into the searched text
    end: int


@dataclass
class FoodVerdict:
    confidence: str | None            # High / Medium / Low, or None if no food at all
    matches: list[FoodMatch] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.confidence is not None

    @property
    def best_match(self) -> FoodMatch | None:
        """The hit to show in the UI: strongest first, then earliest."""
        if not self.matches:
            return None
        return min(self.matches, key=lambda m: (m.strength != "strong", m.start))


@dataclass
class Registration:
    required: bool = False
    url: str | None = None
    closed: bool = False
    evidence: str | None = None

    @property
    def show_signup_badge(self) -> bool:
        return self.required and not self.closed


@dataclass
class EventRow:
    """One occurrence of one event -- the unit the dashboard displays."""

    event_id: int
    instance_id: int
    title: str
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool
    location: str
    room: str
    department: str
    event_types: list[str]
    event_url: str
    description_text: str
    description_html: str
    photo_url: str | None
    span_days: int
    food: FoodVerdict
    registration: Registration

    @property
    def start_date(self) -> date:
        return self.starts_at.date()

    @property
    def location_full(self) -> str:
        return f"{self.location} {self.room}".strip() if self.room else self.location

    def is_today(self, today: date) -> bool:
        return self.start_date == today

    # -- clock state ------------------------------------------------------
    def status(self, now: datetime) -> str:
        """Where this occurrence sits against the clock.

        An all-day run is never "live": a week-long exhibition is not the
        thing you drop everything for, and treating it as urgent would spend
        the accent on the least time-sensitive rows on the board.
        """
        if self.all_day:
            return UPCOMING
        start, ref = _comparable(self.starts_at, now)
        if start > ref:
            return SOON if start - ref <= timedelta(minutes=SOON_MINUTES) else UPCOMING
        if self.ends_at is None:
            end = start + ASSUMED_LENGTH
        else:
            end = _comparable(self.ends_at, now)[0]
        return LIVE if ref < end else PAST

    def countdown(self, now: datetime) -> str:
        """The one line worth putting in orange, or '' when there isn't one."""
        state = self.status(now)
        if state == LIVE:
            if self.ends_at is None:
                return "on now"
            end, ref = _comparable(self.ends_at, now)
            return f"ends in {humanize(end - ref)}"
        if state == SOON:
            start, ref = _comparable(self.starts_at, now)
            return f"starts in {humanize(start - ref)}"
        return ""

    @property
    def sort_key(self) -> tuple:
        return (self.starts_at, CONFIDENCE_ORDER.get(self.food.confidence, 9), self.title)
