# SU Free Food Finder

A local Streamlit dashboard that finds Syracuse University events serving free food.

The campus calendar buries food mentions in prose — there's no way to filter for them, and
the site's own **"Free" tag means free *admission*, not free food**. This reads every event
description in the next two weeks, grades the food evidence, and shows you the sentence it
found so you can judge the call yourself.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py          # opens http://localhost:8501
```

## How it works

```
events.syracuse.edu/api/2/events?days=14&pp=100
        |  5 requests, 1/sec, cached on disk
        v
  486 instance rows  ->  176 unique events        (sufood/normalize.py)
        |  merge each event's occurrences
        v
  score every description                          (sufood/detect.py)
        |  mask -> match -> grade
        v
  one row per occurrence, soonest first            (app.py)
```

The Localist API returns the **full description** in its listing response, so no per-event
page scraping is needed. (Event pages were checked: their only registration markup is
Localist's own `/signup` link and the "I'm Interested" widget, neither of which is a real
registration link. `fetch_event_pages` in `config.yaml` exists as a fallback if the API
ever stops carrying descriptions.)

### Food detection: masking, not penalizing

Most of the difficulty is false positives. The approach that makes this work is **masking**:
misleading phrases are blanked out of the text *before* any matching runs, rather than
subtracting points afterward.

That matters because a description often contains both a trap and a real signal. Penalizing
globally would demote "Free admission. Pizza will be provided." Masking removes only the
words inside "free admission" and leaves the pizza intact.

| Tier | Meaning | Examples |
|---|---|---|
| **High** | One explicit phrase, or a meal on the programme | `lunch provided`, `light lunch`, `pizza`, `refreshments`, `catered`, `while supplies last`, `begins with dinner`, `dinner from 6:30 to 7 pm` |
| **Medium** | Two distinct food nouns, or one plus a modifier | `free` + `cookies` |
| **Low** | A single passing food noun | one mention of `dinner` |
| *(none)* | No food noun at all | — |

Masked before matching: `free admission`, `free parking`, `free-weights`, `served as`
(as in "he *served as* EVP"), `first-come, first-served`, `food pantry`, `food drive`,
`food for thought`.

Vetoed down to Low: `no food`, `food not provided`, `bring your own`.

**A meal with a place on the schedule is a promise.** An event does not have to say
"provided" to be feeding you. *Salaam Shalom* says "Each session begins with dinner from
6:30 to 7 pm" — a specific, scheduled, free meal that an earlier version graded Low and
hid, because a bare `dinner` was its only hit. Three patterns cover this: `begins/starts/
concludes with <meal>`, `followed by <meal>`, and `<meal> from|at <clock time>`.

The second group of patterns in each pair is the guard. "The lecture begins with a
discussion of food systems" and "Doors open at 7 pm; the dinner lecture explores famine"
both put a food word next to a programme verb or a clock without promising a bite, and
both are pinned as negative tests.

**A modifier alone is never food.** "Free" with no food word anywhere means free admission —
exactly the trap the site's Free tag sets. This is why "free parking is available" scores
nothing.

Exhibitions, club sports and multi-day all-day runs only appear at High confidence, and an
ongoing all-day run shows once rather than once per day.

### Announcements are not events

An all-day run with **no event type and no venue** is an application window, a deadline or
a nomination period — not a gathering. It is excluded outright, at any confidence.

This is a structural rule rather than a keyword one, and it exists because the wording can
be perfectly honest while the food is not for you. *2027 Orientation Leader Applications*
says "meals provided", which `detect_food` still grades High in isolation — but the full
sentence is "On-campus housing and meals provided **during summer training and New Student
Orientation sessions**". That is job compensation, at a different event, next July.

Matching on `pay rate` or `$18/hour` would be whack-a-mole; the structure gives it away
instead. In the live window, 16 listings are all-day runs longer than a week, and the 5
with neither a type nor a venue are *all* application windows. Every exhibit and display
carries both, so none are affected. A listing with no venue also can't tell you where to
go, which is reason enough to leave it off a "where do I eat today" board.

### Registration

Localist's `has_register` flag is deliberately **not** used — it drives the "I'm Interested"
button, and in live data it's `False` on events that plainly require registration and `True`
on exhibits that don't. Instead registration comes from `ticket_url`, registration-looking
links in the description, and phrases like *register* / *RSVP* / *sign up*. When the text
says registration has closed, the status shows but the **Sign up!** badge does not.

## Configuration

Every keyword list lives in **`config.yaml`** — edit it and hit Refresh, no code changes.
`get_config()` keys its cache on the file's modification time and the Streamlit cache key
carries it too, so an edit really does take effect without restarting the app:

| Key | What it controls |
|---|---|
| `fetch.window_days` | How far ahead to look (the sidebar slider overrides it) |
| `fetch.rate_limit_seconds` | Minimum gap between requests (1.0 = the site's `Crawl-Delay`) |
| `fetch.cache_ttl_minutes` | How long cached pages stay fresh |
| `detection.strong_signals` | Phrases that alone mean High confidence |
| `detection.weak_signals` | Food nouns — two make Medium, one makes Low |
| `detection.weak_modifiers` | `free`, `complimentary` — only count beside a food noun |
| `detection.masking_phrases` | Blanked out before matching |
| `detection.blocking_phrases` | Hard veto down to Low |
| `detection.restricted_event_types` | Categories needing High to appear |
| `detection.exclude_announcements` | Drop venueless, untyped all-day runs (application windows) |
| `registration.*` | Registration signals, ignores, and closed-phrases |

## Being a good citizen

- **robots.txt is parsed and obeyed** (`/api/` is allowed; `/search` is correctly refused).
- **1 request/second minimum gap**, matching the site's `Crawl-Delay: 1`.
- **Descriptive User-Agent** identifying the project and a contact address.
- **Disk cache** in `.cache/` — a normal run makes 5 requests; reruns make none until the
  TTL expires or you press Refresh.

## Tests

```bash
pytest -q
```

77 tests, offline against a captured API snapshot in `tests/fixtures/`. They pin the
acceptance criteria:

- The **Food for Thought / Goodbye to Silos** event is High, detected through its
  *"light lunch"* text, with the surrounding sentence captured.
- **Turkeys for Veterans** never reaches High.
- **Club sports games** never reach High — they carry the site's `free` tag and no food words.
- **2027 Orientation Leader Applications** is absent from the board even though its
  text still grades High — the announcement rule, not the detector, removes it.
- Free-tagged events with no food wording produce no match at all.

Plus the regression cases that shaped the design: `served as`, `first-come first-served`,
`free-weights`, `food pantry`, and masking-vs-penalizing.

## Layout

```
app.py              Streamlit UI
config.yaml         keyword lists and tunables
sufood/
  config.py         loads + compiles config.yaml
  fetch.py          rate-limited, cached, robots-aware HTTP
  normalize.py      dedupe, instance expansion, HTML cleaning
  detect.py         food scoring + registration
  models.py         EventRow, FoodVerdict, Registration
tests/              pytest suite + API fixture
```
