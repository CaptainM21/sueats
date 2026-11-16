"""Food and registration detection.

The core design decision here is **masking rather than global penalizing**.

A naive scorer that subtracts points whenever it sees "free admission" would
wrongly demote an event whose description says *both* "free admission" and
"pizza will be provided" -- a very common combination on this calendar.
Instead, every configured masking phrase is blanked out of the text *before*
any signal matching runs. That consumes the misleading word in place ("free
admission" no longer yields a `free` hit; "served as EVP" no longer yields a
`served` hit) while leaving every other word in the description intact and
still matchable.
"""
from __future__ import annotations

import html as html_lib
import re

from .config import DetectionConfig, RegistrationConfig
from .models import HIGH, LOW, MEDIUM, FoodMatch, FoodVerdict, Registration

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WHITESPACE = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_ANCHOR = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def clean_text(value: str | None) -> str:
    """HTML -> plain text, with entities resolved and mojibake repaired.

    Localist's own `description_text` field contains U+FFFD replacement
    characters where smart quotes were mangled upstream, so we prefer to
    derive text from the `description` HTML and clean it here.
    """
    if not value:
        return ""
    text = _TAG.sub(" ", value)
    text = html_lib.unescape(text)
    # Repair the two mojibake forms seen in live data.
    text = text.replace("�", "'").replace(" ", " ")
    return _WHITESPACE.sub(" ", text).strip()


def _sentence_at(text: str, start: int, end: int) -> str:
    """The full sentence containing [start:end], for display as evidence."""
    left = 0
    for m in _SENTENCE_SPLIT.finditer(text, 0, start):
        left = m.end()
    right_match = _SENTENCE_SPLIT.search(text, end)
    right = right_match.start() if right_match else len(text)
    return text[left:right].strip()


def _mask(text: str, patterns) -> str:
    """Blank out misleading phrases, preserving every character offset."""
    masked = text
    for pattern in patterns:
        masked = pattern.sub(lambda m: " " * (m.end() - m.start()), masked)
    return masked


def _collect(masked: str, original: str, patterns, strength: str) -> list[FoodMatch]:
    matches = []
    for pattern in patterns:
        for m in pattern.finditer(masked):
            phrase = m.group(0).strip()
            if not phrase:
                continue
            matches.append(FoodMatch(
                phrase=phrase,
                sentence=_sentence_at(original, m.start(), m.end()),
                strength=strength,
                start=m.start(),
                end=m.end(),
            ))
    return matches


def _dedupe(matches: list[FoodMatch]) -> list[FoodMatch]:
    """Drop hits fully contained inside another hit of the same strength."""
    kept: list[FoodMatch] = []
    for m in sorted(matches, key=lambda x: (x.start, -(x.end - x.start))):
        if any(k.start <= m.start and m.end <= k.end and k.strength == m.strength for k in kept):
            continue
        kept.append(m)
    return kept


def detect_food(text: str, cfg: DetectionConfig) -> FoodVerdict:
    """Grade a block of text for free-food signals.

    High   -- at least one strong signal
    Medium -- two or more distinct weak food nouns, or one plus a modifier
              such as "free"
    Low    -- exactly one weak food noun, or any result vetoed by a
              blocking phrase
    None   -- no food noun at all

    A modifier on its own never produces a match. "Free" with no food word
    anywhere means free *admission* -- the trap the site's own "Free" tag
    sets, and the reason "free parking is available" must score nothing.
    """
    text = clean_text(text) if "<" in (text or "") else _WHITESPACE.sub(" ", text or "").strip()
    if not text:
        return FoodVerdict(confidence=None)

    masked = _mask(text, cfg.masking_phrases)

    strong = _dedupe(_collect(masked, text, cfg.strong_signals, "strong"))
    weak = _dedupe(_collect(masked, text, cfg.weak_signals, "weak"))
    modifiers = _dedupe(_collect(masked, text, cfg.weak_modifiers, "weak"))

    # Blocking phrases are checked against the unmasked text: an explicit
    # "no food provided" must still veto even if it overlaps a masked phrase.
    blocked = [p.search(text).group(0) for p in cfg.blocking_phrases if p.search(text)]

    distinct_weak = {m.phrase.lower() for m in weak}

    if strong:
        confidence = HIGH
    elif not distinct_weak:
        confidence = None          # modifiers alone are never food
    elif len(distinct_weak) >= 2 or modifiers:
        confidence = MEDIUM
    else:
        confidence = LOW

    # Modifiers are only worth showing as evidence once a food noun exists.
    matches = _dedupe(strong + weak + (modifiers if distinct_weak else []))

    if confidence is None:
        return FoodVerdict(confidence=None)

    if blocked and confidence is not None:
        confidence = LOW

    return FoodVerdict(confidence=confidence, matches=matches, blocked_by=blocked)


def is_restricted(event_types: list[str], all_day: bool, span_days: int,
                  cfg: DetectionConfig) -> bool:
    """Whether this item needs High confidence to earn a place on the board.

    "Ongoing" means a continuous multi-day run -- an exhibit, a display, an
    application window. A weekly meeting at 6pm is *not* ongoing: it is a
    discrete event that happens to repeat, so it is judged on its own merits
    at whatever confidence its wording supports.
    """
    if set(event_types) & cfg.restricted_event_types:
        return True
    return all_day and span_days > cfg.ongoing_span_days


def detect_registration(text: str, html: str, ticket_url: str, event_url: str,
                        localist_url: str, cfg: RegistrationConfig) -> Registration:
    """Decide whether an event needs signing up for, and where to do it.

    Localist's `has_register` flag is deliberately not consulted: it drives the
    "I'm Interested" widget, and live data shows it False on events that plainly
    require registration and True on exhibits that do not.
    """
    haystack = clean_text(text)
    # Remove the Localist widget wording before looking for real signals.
    for pattern in cfg.ignore:
        haystack = pattern.sub(" ", haystack)

    evidence = None
    for pattern in cfg.signals:
        m = pattern.search(haystack)
        if m:
            evidence = _sentence_at(haystack, m.start(), m.end())
            break

    ticket_url = (ticket_url or "").strip()
    required = bool(evidence) or bool(ticket_url)
    if not required:
        return Registration(required=False)

    closed = any(p.search(haystack) for p in cfg.closed_phrases)

    url = ticket_url or _registration_link_in(html) or (event_url or "").strip() or localist_url

    return Registration(required=True, url=url or None, closed=closed, evidence=evidence)


def _registration_link_in(html: str) -> str | None:
    """A link in the description whose text or href looks like registration."""
    if not html:
        return None
    signal = re.compile(r"regist|rsvp|sign[- ]?up|ticket|eventbrite", re.IGNORECASE)
    for href, label in _ANCHOR.findall(html):
        if href.startswith("mailto:"):
            continue
        if signal.search(href) or signal.search(clean_text(label)):
            return href
    return None
