"""Data structures shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

HIGH, MEDIUM, LOW = "High", "Medium", "Low"
CONFIDENCE_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}


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

    @property
    def sort_key(self) -> tuple:
        return (self.starts_at, CONFIDENCE_ORDER.get(self.food.confidence, 9), self.title)
