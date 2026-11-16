"""Food + registration detection tests.

Acceptance cases come from the original request; they run against API data
captured in tests/fixtures/ so the suite is offline and deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sufood.config import load_config
from sufood.detect import detect_food, detect_registration
from sufood.models import HIGH, LOW, MEDIUM

FIXTURE = Path(__file__).parent / "fixtures" / "api_events_raw.json"
TEST_EVENT_SLUG = "food-for-thought-say-goodbye-to-silos-building-connections-across-su"


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def raw_events():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _verdict(cfg, event):
    text = event["title"] + ". " + (event.get("description_text") or "")
    return detect_food(text, cfg.detection)


def _find(raw_events, needle):
    hits = [e for e in raw_events if needle.lower() in e["title"].lower()]
    assert hits, f"fixture is missing an event matching {needle!r}"
    return hits[0]


# --------------------------------------------------------------------------
# Acceptance criteria from the request
# --------------------------------------------------------------------------

def test_food_for_thought_detected_via_light_lunch(cfg, raw_events):
    """The named test event must be High, found through its 'light lunch' text."""
    event = next(e for e in raw_events if TEST_EVENT_SLUG in e["localist_url"])
    verdict = _verdict(cfg, event)

    assert verdict.confidence == HIGH
    phrases = " | ".join(m.phrase.lower() for m in verdict.matches)
    assert "light lunch" in phrases, f"expected 'light lunch' among: {phrases}"
    assert verdict.best_match.sentence, "must capture the surrounding sentence"


def test_turkeys_for_veterans_is_not_high(cfg, raw_events):
    event = _find(raw_events, "Turkeys for Veterans")
    assert _verdict(cfg, event).confidence != HIGH


def test_club_sports_games_are_not_high(cfg, raw_events):
    """Club sports carry the site's `free` tag but serve no food."""
    games = [e for e in raw_events if e["title"].lower().startswith("club ")]
    assert games, "fixture should contain club sports events"
    for game in games:
        assert _verdict(cfg, game).confidence != HIGH, f"false positive: {game['title']}"


def test_free_tag_alone_never_implies_food(cfg, raw_events):
    """Events flagged free=True with no food wording must not register at all."""
    seen = {}
    for e in raw_events:
        seen.setdefault(e["id"], e)
    free_tagged = [e for e in seen.values() if e.get("free")]
    assert free_tagged
    food_words = ("food", "lunch", "dinner", "pizza", "snack", "refreshment",
                  "breakfast", "coffee", "dessert", "treat", "cookie")
    no_food_words = [
        e for e in free_tagged
        if not any(w in (e.get("description_text") or "").lower() for w in food_words)
    ]
    assert no_food_words, "expected some free-tagged events with no food words"
    for e in no_food_words:
        assert _verdict(cfg, e).confidence is None, f"free tag leaked a match: {e['title']}"


# --------------------------------------------------------------------------
# Signal grading
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "A light lunch will be provided.",
    "Free food for all attendees!",
    "Pizza will be served.",
    "Refreshments provided.",
    "The event is catered.",
    "Snacks and drinks, while supplies last.",
    "Lunch is provided for registered guests.",
    "Come enjoy free pizza.",
])
def test_strong_signals_give_high(cfg, text):
    assert detect_food(text, cfg.detection).confidence == HIGH, text


def test_two_weak_signals_give_medium(cfg):
    # "free lunch" would be a STRONG signal, so this pairs two genuinely weak ones.
    v = detect_food("A free workshop, with coffee.", cfg.detection)
    assert v.confidence == MEDIUM
    assert len({m.phrase.lower() for m in v.matches}) >= 2


def test_single_weak_signal_gives_low(cfg):
    assert detect_food("Lunch options are nearby.", cfg.detection).confidence == LOW


@pytest.mark.parametrize("text", [
    "This workshop is free.",
    "Free and complimentary for all students.",
    "Free event, no cost to attend.",
])
def test_modifier_without_a_food_noun_is_never_food(cfg, text):
    """'Free' with no food word means free admission -- the Free-tag trap."""
    assert detect_food(text, cfg.detection).confidence is None, text


def test_modifier_lifts_a_single_food_noun_to_medium(cfg):
    v = detect_food("Free cookies at the front desk.", cfg.detection)
    assert v.confidence == MEDIUM


def test_no_signal_gives_none(cfg):
    assert detect_food("A lecture on medieval architecture.", cfg.detection).confidence is None


# --------------------------------------------------------------------------
# Masking: the phrase is consumed, the rest of the text survives
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Free admission to the public.",
    "Free parking is available in the Q lot.",
    "This event is free to attend.",
    "Free and open to the public.",
])
def test_free_admission_variants_are_not_food(cfg, text):
    assert detect_food(text, cfg.detection).confidence is None, text


def test_masking_does_not_suppress_a_real_food_mention(cfg):
    """The key design property: one masked phrase must not demote a real signal."""
    v = detect_food("Free admission. Pizza will be provided.", cfg.detection)
    assert v.confidence == HIGH
    assert "pizza" in " ".join(m.phrase.lower() for m in v.matches)


@pytest.mark.parametrize("text", [
    "He served as Executive Vice President of Digital.",
    "Seating is first-come, first-served.",
    "Space is available on a first come first served basis.",
])
def test_served_false_positives_are_masked(cfg, text):
    assert detect_food(text, cfg.detection).confidence != HIGH, text


def test_free_weights_is_not_a_free_signal(cfg):
    assert detect_food("A full-body free-weights workout.", cfg.detection).confidence is None


@pytest.mark.parametrize("text", [
    "Donate to the campus food pantry.",
    "A canned food drive for the holidays.",
    "A panel on food insecurity in Central New York.",
])
def test_food_charity_language_is_not_free_food(cfg, text):
    assert detect_food(text, cfg.detection).confidence != HIGH, text


def test_teaching_does_not_trigger_the_tea_signal(cfg):
    assert detect_food("A teaching workshop for new instructors.", cfg.detection).confidence is None


# --------------------------------------------------------------------------
# Blocking phrases
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Free admission, no food provided.",
    "Lunch will not be provided; bring your own.",
    "Food is not provided at this session.",
])
def test_blocking_phrases_cap_at_low(cfg, text):
    v = detect_food(text, cfg.detection)
    assert v.confidence == LOW, text
    assert v.blocked_by


# --------------------------------------------------------------------------
# Evidence capture
# --------------------------------------------------------------------------

def test_match_captures_phrase_and_surrounding_sentence(cfg):
    text = "Welcome everyone. CART and a light lunch will be provided. Questions to Chris."
    m = detect_food(text, cfg.detection).best_match
    assert "light lunch" in m.sentence.lower()
    assert "Welcome everyone" not in m.sentence
    assert "Questions to Chris" not in m.sentence
    assert text[m.start:m.end].lower() == m.phrase.lower()


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

def test_registration_from_ticket_url(cfg):
    r = detect_registration(
        text="Register in the Wellness Portal today!",
        html="", ticket_url="https://bewell.ese.syr.edu/Program/X", event_url="",
        localist_url="https://events.syracuse.edu/event/cardio", cfg=cfg.registration,
    )
    assert r.required and r.url == "https://bewell.ese.syr.edu/Program/X"
    assert r.show_signup_badge


def test_registration_detected_from_text_without_api_flag(cfg):
    r = detect_registration(
        text="Please RSVP by Friday.", html="", ticket_url="", event_url="",
        localist_url="https://events.syracuse.edu/event/x", cfg=cfg.registration,
    )
    assert r.required
    assert r.url == "https://events.syracuse.edu/event/x"


def test_im_interested_is_not_registration(cfg):
    r = detect_registration(
        text="Click I am Interested to follow this event.", html="", ticket_url="",
        event_url="", localist_url="https://events.syracuse.edu/event/x", cfg=cfg.registration,
    )
    assert not r.required


def test_closed_registration_suppresses_signup_badge(cfg):
    r = detect_registration(
        text="Registration is now closed. We will accommodate same day attendance.",
        html="", ticket_url="", event_url="",
        localist_url="https://events.syracuse.edu/event/x", cfg=cfg.registration,
    )
    assert r.required and r.closed
    assert not r.show_signup_badge


def test_registration_link_pulled_from_description_html(cfg):
    html = '<p>Please <a href="https://forms.syr.edu/signup">register here</a> to attend.</p>'
    r = detect_registration(text="Please register here to attend.", html=html, ticket_url="",
                            event_url="", localist_url="https://events.syracuse.edu/event/x",
                            cfg=cfg.registration)
    assert r.required and r.url == "https://forms.syr.edu/signup"


def test_no_registration_signal(cfg):
    r = detect_registration(text="Drop in any time.", html="", ticket_url="", event_url="",
                            localist_url="https://events.syracuse.edu/event/x",
                            cfg=cfg.registration)
    assert not r.required and r.url is None
