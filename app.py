"""SU Free Food Finder -- a dashboard of Syracuse University events serving food.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta

import streamlit as st

from sufood.config import DEFAULT_CONFIG_PATH, get_config
from sufood.fetch import PoliteSession, fetch_events
from sufood.models import HIGH, LOW, MEDIUM, EventRow
from sufood.normalize import build_rows

CONFIDENCE_LEVELS = [HIGH, MEDIUM, LOW]

STYLES = """
<style>
  :root {
    --su-orange:   #D94F00;   /* Syracuse Orange -- the one accent */
    --ink:         #1A1613;
    --ink-soft:    #5C534C;
    --ink-faint:   #8A7F77;
    --surface:     #FFFFFF;
    --surface-sun: #FDF8F4;   /* warm neutral, biased toward the accent */
    --rule:        #EBE2DB;
    --rule-strong: #D9CCC2;
    /* Semantic confidence colors, deliberately not the accent hue. */
    --high-fg:  #0E6B45;     --high-bg:  #E7F4EC; --high-br:  #BFE0CC;
    --med-fg:   #8A5A06;     --med-bg:   #FBF0DC; --med-br:   #EDD6AC;
    --low-fg:   #5A6572;     --low-bg:   #EEF1F4; --low-br:   #D5DBE2;
  }

  .block-container { padding-top: 2.2rem; max-width: 1180px; }

  /* ---- masthead ---- */
  .ff-mast { border-bottom: 2px solid var(--su-orange); padding-bottom: .6rem; margin-bottom: .2rem; }
  .ff-mast h1 {
    font-size: 1.9rem; font-weight: 700; letter-spacing: -.02em;
    color: var(--ink); margin: 0; text-wrap: balance;
  }
  .ff-mast p { color: var(--ink-soft); font-size: .92rem; margin: .3rem 0 0; }

  /* ---- summary strip ---- */
  .ff-stats { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1rem 0 1.4rem; }
  .ff-stat {
    flex: 1 1 130px; background: var(--surface-sun); border: 1px solid var(--rule);
    border-radius: 8px; padding: .65rem .8rem;
  }
  .ff-stat .n {
    font-size: 1.55rem; font-weight: 700; line-height: 1.1;
    font-variant-numeric: tabular-nums; color: var(--ink);
  }
  .ff-stat .k {
    font-size: .68rem; text-transform: uppercase; letter-spacing: .09em;
    color: var(--ink-faint); margin-top: .15rem;
  }
  .ff-stat.today { background: #FFF2E8; border-color: #F3C9A8; }
  .ff-stat.today .n { color: var(--su-orange); }

  /* ---- day heading ---- */
  .ff-day {
    display: flex; align-items: baseline; gap: .6rem;
    margin: 1.6rem 0 .6rem; padding-bottom: .3rem;
    border-bottom: 1px solid var(--rule);
  }
  .ff-day .d { font-size: .95rem; font-weight: 650; color: var(--ink); }
  .ff-day .c { font-size: .76rem; color: var(--ink-faint); }

  /* ---- event card ---- */
  .ff-card {
    background: var(--surface); border: 1px solid var(--rule);
    border-left: 3px solid var(--rule-strong);
    border-radius: 8px 8px 0 0; border-bottom: none;
    padding: .85rem 1rem .7rem;
  }
  /* Today reads through the stripe and the TODAY timestamp, so the card
     keeps the same ground as its expander foot. */
  .ff-card.is-today { border-left-color: var(--su-orange); }
  .ff-card.is-today .ff-meta .t { color: var(--su-orange); }

  .ff-head { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; }
  .ff-title { font-size: 1.02rem; font-weight: 650; line-height: 1.35; margin: 0; text-wrap: balance; }
  .ff-title a { color: var(--ink); text-decoration: none; }
  .ff-title a:hover { color: var(--su-orange); text-decoration: underline; }

  .ff-meta {
    display: flex; flex-wrap: wrap; gap: .4rem .9rem;
    font-size: .82rem; color: var(--ink-soft); margin-top: .35rem;
  }
  .ff-meta .t { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--ink); }
  .ff-dept { font-size: .76rem; color: var(--ink-faint); margin-top: .2rem; }

  /* evidence: the matched phrase inside its own sentence */
  .ff-evidence {
    margin-top: .6rem; padding: .5rem .7rem; border-radius: 6px;
    background: var(--surface-sun); border: 1px solid var(--rule);
    font-size: .85rem; line-height: 1.5; color: var(--ink-soft);
  }
  .ff-evidence b { color: var(--ink); background: #FFE9BF; padding: 0 .18em; border-radius: 2px; }
  .ff-evidence .lbl {
    display: block; font-size: .66rem; text-transform: uppercase;
    letter-spacing: .09em; color: var(--ink-faint); margin-bottom: .25rem;
  }

  /* pills -- state encoded in form, not only in words */
  .ff-pill {
    display: inline-block; white-space: nowrap; font-size: .7rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .05em;
    padding: .2rem .5rem; border-radius: 999px; border: 1px solid;
  }
  .p-high { color: var(--high-fg); background: var(--high-bg); border-color: var(--high-br); }
  .p-med  { color: var(--med-fg);  background: var(--med-bg);  border-color: var(--med-br); }
  .p-low  { color: var(--low-fg);  background: var(--low-bg);  border-color: var(--low-br); }

  .ff-reg { margin-top: .55rem; font-size: .82rem; display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
  .ff-signup {
    display: inline-block; background: var(--su-orange); color: #fff !important;
    font-size: .74rem; font-weight: 700; padding: .25rem .6rem;
    border-radius: 5px; text-decoration: none;
  }
  .ff-signup:hover { background: #B84200; }
  .ff-closed { color: var(--ink-faint); font-style: italic; }
  .ff-blocked { color: var(--med-fg); font-size: .78rem; margin-top: .4rem; }

  /* The description expander is the foot of the card above it, not a
     separate object -- it shares the card's edges and left stripe. */
  div[data-testid="stExpander"] {
    margin: 0 0 .6rem; border: 1px solid var(--rule) !important;
    border-left: 3px solid var(--rule-strong) !important;
    border-radius: 0 0 8px 8px !important; background: var(--surface);
  }
  div[data-testid="stExpander"] details { border: none !important; background: transparent !important; }
  div[data-testid="stExpander"] summary {
    padding: .35rem 1rem !important; font-size: .78rem !important;
    color: var(--ink-faint) !important;
  }
  div[data-testid="stExpander"] summary:hover { color: var(--su-orange) !important; }
  div[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    padding: 0 1rem .7rem; font-size: .85rem; color: var(--ink-soft);
  }
  /* Scoped to the results column so the sidebar keeps its own spacing. */
  [data-testid="stMain"] div[data-testid="stVerticalBlock"] { gap: 0 !important; }

  .ff-empty {
    border: 1px dashed var(--rule-strong); border-radius: 8px;
    padding: 2rem 1rem; text-align: center; color: var(--ink-soft);
  }

  @media (max-width: 640px) {
    .ff-head { flex-direction: column; gap: .4rem; }
  }
</style>
"""

PILL_CLASS = {HIGH: "p-high", MEDIUM: "p-med", LOW: "p-low"}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def current_config_mtime() -> float:
    """config.yaml's mtime, so an edit invalidates every layer of cache."""
    try:
        return DEFAULT_CONFIG_PATH.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def load_rows(window_days: int, force: bool, _bust: int,
              config_mtime: float) -> tuple[list[EventRow], dict]:
    """`config_mtime` is unused in the body -- it is here purely so that
    editing config.yaml changes Streamlit's cache key and the rows rebuild.
    It must NOT be underscore-prefixed: st.cache_data excludes those from the
    key, which is why `_bust` alone never invalidated anything and the Refresh
    button has to call load_rows.clear()."""
    cfg = get_config()
    session = PoliteSession(cfg)
    if force:
        session.clear_cache()
    raw, stats = fetch_events(cfg, session, window_days=window_days, force_refresh=force)
    rows = build_rows(raw, cfg, window_days=window_days)
    meta = {
        "events_scanned": len({e["id"] for e in raw}),
        "requests": stats.requests_made,
        "cache_hits": stats.cache_hits,
        "fetched_at": datetime.now(),
    }
    return rows, meta


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def highlight(sentence: str, phrase: str) -> str:
    """Escape the sentence, then bold the matched phrase inside it."""
    safe = html.escape(sentence)
    if not phrase:
        return safe
    pattern = re.compile(re.escape(html.escape(phrase)), re.IGNORECASE)
    return pattern.sub(lambda m: f"<b>{m.group(0)}</b>", safe, count=1)


def format_time(row: EventRow) -> str:
    if row.all_day:
        return "All day"
    start = row.starts_at.strftime("%I:%M %p").lstrip("0")
    if row.ends_at:
        return f"{start} – {row.ends_at.strftime('%I:%M %p').lstrip('0')}"
    return start


def render_card(row: EventRow, today: date) -> str:
    match = row.food.best_match
    pill = PILL_CLASS.get(row.food.confidence, "p-low")
    is_today = row.is_today(today)

    bits = [
        '<div class="ff-card{}">'.format(" is-today" if is_today else ""),
        '  <div class="ff-head">',
        '    <div style="flex:1 1 auto;min-width:0">',
        '      <p class="ff-title"><a href="{}" target="_blank" rel="noopener">{}</a></p>'.format(
            html.escape(row.event_url), html.escape(row.title)),
        '      <div class="ff-meta">',
        '        <span class="t">{}{}</span>'.format(
            "TODAY · " if is_today else "", html.escape(format_time(row))),
        '        <span>{}</span>'.format(html.escape(row.location_full)),
        '      </div>',
        '      <div class="ff-dept">{}</div>'.format(html.escape(row.department)),
        '    </div>',
        '    <span class="ff-pill {}">{}</span>'.format(pill, html.escape(row.food.confidence)),
        '  </div>',
    ]

    if match:
        bits.append(
            '  <div class="ff-evidence"><span class="lbl">Food mention</span>{}</div>'.format(
                highlight(match.sentence, match.phrase)))

    if row.food.blocked_by:
        bits.append('  <div class="ff-blocked">⚠ This listing says food is not provided.</div>')

    reg = row.registration
    if reg.required:
        if reg.closed:
            bits.append('  <div class="ff-reg"><span class="ff-closed">'
                        'Registration closed — walk-ins may be accommodated.</span></div>')
        else:
            bits.append(
                '  <div class="ff-reg"><span>Registration required</span>'
                '<a class="ff-signup" href="{}" target="_blank" rel="noopener">Sign up!</a></div>'
                .format(html.escape(reg.url or row.event_url)))
    else:
        bits.append('  <div class="ff-reg"><span style="color:var(--ink-faint)">'
                    'No registration needed — just show up.</span></div>')

    bits.append('</div>')
    return "\n".join(bits)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = get_config()
    st.set_page_config(page_title=cfg.ui.page_title, page_icon="🍕", layout="wide")
    st.markdown(STYLES, unsafe_allow_html=True)

    if "bust" not in st.session_state:
        st.session_state.bust = 0

    # -- sidebar ----------------------------------------------------------
    with st.sidebar:
        st.markdown("### Filters")
        window_days = st.slider("Look ahead (days)", 1, 30, cfg.fetch.window_days,
                                help="How far into the future to search.")

        if st.button("↻ Refresh from events.syracuse.edu", use_container_width=True):
            st.session_state.bust += 1
            load_rows.clear()
            st.rerun()

    with st.spinner("Reading the Syracuse University events calendar…"):
        try:
            rows, meta = load_rows(window_days, st.session_state.bust > 0,
                                  st.session_state.bust, current_config_mtime())
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            st.error(f"Could not load events: {exc}")
            st.stop()

    today = date.today()

    # -- remaining filters, built from the data we actually have ----------
    with st.sidebar:
        confidences = st.multiselect(
            "Confidence", CONFIDENCE_LEVELS, default=list(cfg.ui.default_confidences),
            help="High = an explicit phrase like “lunch provided”. "
                 "Low = a single passing food word.")

        only_today = st.checkbox("Happening today only", value=False)
        reg_choice = st.radio("Registration", ["Any", "Not required", "Required"],
                              index=0, horizontal=False)

        locations = sorted({r.location for r in rows})
        chosen_locations = st.multiselect("Location", locations, default=[])

        earliest = min((r.start_date for r in rows), default=today)
        latest = max((r.start_date for r in rows), default=today + timedelta(days=window_days))
        date_range = st.date_input("Date range", value=(earliest, latest),
                                   min_value=earliest, max_value=latest)

        st.markdown("---")
        st.caption(
            f"Scanned **{meta['events_scanned']}** events · "
            f"{meta['requests']} request(s), {meta['cache_hits']} from cache\n\n"
            f"Updated {meta['fetched_at'].strftime('%b %d, %I:%M %p').replace(' 0', ' ')}"
        )
        st.caption("Keyword lists live in `config.yaml`.")

    # -- apply filters ----------------------------------------------------
    visible = [r for r in rows if r.food.confidence in confidences]
    if only_today:
        visible = [r for r in visible if r.is_today(today)]
    if reg_choice == "Required":
        visible = [r for r in visible if r.registration.required]
    elif reg_choice == "Not required":
        visible = [r for r in visible if not r.registration.required]
    if chosen_locations:
        visible = [r for r in visible if r.location in chosen_locations]
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        start, end = date_range
        visible = [r for r in visible if start <= r.start_date <= end]

    # -- masthead + summary ----------------------------------------------
    st.markdown(
        '<div class="ff-mast"><h1>🍕 SU Free Food Finder</h1>'
        f'<p>Events at Syracuse University serving food in the next {window_days} days. '
        'Every match shows the sentence it came from, so you can judge it yourself.</p></div>',
        unsafe_allow_html=True)

    counts = {level: sum(1 for r in visible if r.food.confidence == level)
              for level in CONFIDENCE_LEVELS}
    today_count = sum(1 for r in visible if r.is_today(today))
    st.markdown(
        '<div class="ff-stats">'
        f'<div class="ff-stat today"><div class="n">{today_count}</div><div class="k">Today</div></div>'
        f'<div class="ff-stat"><div class="n">{counts[HIGH]}</div><div class="k">High confidence</div></div>'
        f'<div class="ff-stat"><div class="n">{counts[MEDIUM]}</div><div class="k">Medium</div></div>'
        f'<div class="ff-stat"><div class="n">{counts[LOW]}</div><div class="k">Low</div></div>'
        f'<div class="ff-stat"><div class="n">{len(visible)}</div><div class="k">Total shown</div></div>'
        '</div>',
        unsafe_allow_html=True)

    if not visible:
        st.markdown(
            '<div class="ff-empty"><strong>No matching events.</strong><br>'
            'Try widening the date range, or switch Low confidence on in the sidebar.</div>',
            unsafe_allow_html=True)
        return

    # -- results, grouped by day, soonest first ---------------------------
    current_day = None
    for row in visible:
        if row.start_date != current_day:
            current_day = row.start_date
            label = current_day.strftime("%A, %B %d").replace(" 0", " ")
            if current_day == today:
                label = f"Today — {label}"
            elif current_day == today + timedelta(days=1):
                label = f"Tomorrow — {label}"
            same_day = sum(1 for r in visible if r.start_date == current_day)
            st.markdown(
                f'<div class="ff-day"><span class="d">{html.escape(label)}</span>'
                f'<span class="c">{same_day} event{"s" if same_day != 1 else ""}</span></div>',
                unsafe_allow_html=True)

        st.markdown(render_card(row, today), unsafe_allow_html=True)
        with st.expander("Full description"):
            st.write(row.description_text or "_No description provided._")
            st.caption(f"Event types: {', '.join(row.event_types) or '—'}")


if __name__ == "__main__":
    main()
