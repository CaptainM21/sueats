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
  488 instance rows  ->  178 unique events        (sufood/normalize.py)
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
| **High** | One explicit phrase | `lunch provided`, `light lunch`, `pizza`, `refreshments`, `catered`, `while supplies last` |
| **Medium** | Two distinct food nouns, or one plus a modifier | `free` + `cookies` |
| **Low** | A single passing food noun | one mention of `dinner` |
| *(none)* | No food noun at all | — |

Masked before matching: `free admission`, `free parking`, `free-weights`, `served as`
(as in "he *served as* EVP"), `first-come, first-served`, `food pantry`, `food drive`,
`food for thought`.

Vetoed down to Low: `no food`, `food not provided`, `bring your own`.

**A modifier alone is never food.** "Free" with no food word anywhere means free admission —
exactly the trap the site's Free tag sets. This is why "free parking is available" scores
nothing.

Exhibitions, club sports and multi-day all-day runs only appear at High confidence, and an
ongoing all-day run shows once rather than once per day.

### Registration

Localist's `has_register` flag is deliberately **not** used — it drives the "I'm Interested"
button, and in live data it's `False` on events that plainly require registration and `True`
on exhibits that don't. Instead registration comes from `ticket_url`, registration-looking
links in the description, and phrases like *register* / *RSVP* / *sign up*. When the text
says registration has closed, the status shows but the **Sign up!** badge does not.

## Configuration

Every keyword list lives in **`config.yaml`** — edit it and hit Refresh, no code changes:

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

56 tests, offline against a captured API snapshot in `tests/fixtures/`. They pin the
acceptance criteria:

- The **Food for Thought / Goodbye to Silos** event is High, detected through its
  *"light lunch"* text, with the surrounding sentence captured.
- **Turkeys for Veterans** never reaches High.
- **Club sports games** never reach High — they carry the site's `free` tag and no food words.
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
