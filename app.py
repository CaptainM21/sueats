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
from sufood.models import HIGH, LIVE, LOW, MEDIUM, SOON, EventRow
from sufood.normalize import build_rows

CONFIDENCE_LEVELS = [HIGH, MEDIUM, LOW]

# ---------------------------------------------------------------------------
# Design tokens
#
# Three typefaces, three jobs: Bricolage Grotesque for display, Public Sans
# (the face of US civic digital services) for everything you read, IBM Plex
# Mono for anything that is a number or a clock. Syracuse Orange is reserved
# for live state and the one call to action -- nothing else ever wears it.
# ---------------------------------------------------------------------------

_FONTS = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,600;12..96,700"
    "&family=IBM+Plex+Mono:wght@400;500;600"
    "&family=Public+Sans:wght@400;500;600;700"
    "&display=swap');"
)

LIGHT_TOKENS = """
  --ground:#FBFAF9; --surface:#FFFFFF; --surface-2:#F4F1ED;
  --ink:#17120F; --ink-2:#5A524C; --ink-3:#8C827B;
  --rule:#E8E3DE; --rule-2:#D7CFC8;
  --orange:#D94F00; --orange-deep:#A83C00; --on-orange:#FFFFFF;
  --mark:#FFE4B8;
  --high-fg:#0E6B45; --high-bg:#E7F4EC; --high-br:#BFE0CC;
  --med-fg:#8A5A06;  --med-bg:#FBF0DC;  --med-br:#EDD6AC;
  --low-fg:#5A6572;  --low-bg:#EEF1F4;  --low-br:#D5DBE2;
  --shadow:0 1px 2px rgba(23,18,15,.05), 0 10px 28px -14px rgba(23,18,15,.22);
  --f-display:'Bricolage Grotesque','Public Sans',system-ui,sans-serif;
  --f-body:'Public Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  --f-mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --t1:.6875rem; --t2:.75rem; --t3:.8125rem; --t4:.9375rem;
  --t5:1.0625rem; --t6:1.3125rem; --t7:1.75rem; --t8:2.25rem;
  --s1:.25rem; --s2:.5rem; --s3:.75rem; --s4:1rem; --s5:1.5rem; --s6:2rem; --s7:3rem;
  --r:10px; --thumb:64px;
"""

# Only colors are redefined -- every layout and type token above still stands.
DARK_TOKENS = """
  --ground:#15120F; --surface:#1E1A16; --surface-2:#241F1A;
  --ink:#F5F1ED; --ink-2:#B5ABA2; --ink-3:#8A7F76;
  --rule:#2E2823; --rule-2:#3D3630;
  --orange:#FF7A33; --orange-deep:#FF9459; --on-orange:#1A0E06;
  --mark:#4A3514;
  --high-fg:#4ECB8F; --high-bg:#122A1F; --high-br:#1E4433;
  --med-fg:#E8B45A;  --med-bg:#2C2314;  --med-br:#4A3A1C;
  --low-fg:#93A2B4;  --low-bg:#1C2128;  --low-br:#2F3842;
  --shadow:0 1px 2px rgba(0,0,0,.45), 0 10px 28px -14px rgba(0,0,0,.7);
"""

COMPONENTS = """
  /* Everything this app renders lives inside .ff-scope. That is not only
     namespacing: Streamlit styles markdown headings through
     [data-testid="stMarkdownContainer"] h2, specificity (0,1,1), which beats a
     bare .ff-dayh (0,1,0) and silently takes back every heading rule below.
     The extra class puts these at (0,2,0) and up, so they win. */

  .block-container{max-width:940px;padding-top:var(--s5);padding-bottom:var(--s7);}
  [data-testid="stHeader"]{background:transparent;}
  .ff-scope{font-family:var(--f-body);}

  /* ---- masthead ---- */
  .ff-scope .ff-mast{border-bottom:1px solid var(--rule);padding-bottom:var(--s4);
    margin-bottom:var(--s4);}
  .ff-scope .ff-eyebrow{font-family:var(--f-mono);font-size:var(--t1);font-weight:500;
    text-transform:uppercase;letter-spacing:.16em;color:var(--ink-3);}
  .ff-scope .ff-mast h1{font-family:var(--f-display);font-size:var(--t8);font-weight:700;
    letter-spacing:-.028em;line-height:1.04;color:var(--ink);margin:var(--s2) 0 0;
    padding:0;text-wrap:balance;}
  .ff-scope .ff-lede{font-size:var(--t4);line-height:1.6;color:var(--ink-2);
    margin:var(--s3) 0 0;max-width:62ch;}

  /* ---- summary rail ---- */
  .ff-scope .ff-rail{display:flex;flex-wrap:wrap;align-items:baseline;gap:var(--s2) var(--s5);
    margin:0 0 var(--s4);padding-bottom:var(--s3);border-bottom:1px solid var(--rule);}
  .ff-scope .ff-fig{font-size:var(--t3);color:var(--ink-2);}
  .ff-scope .ff-fig b{font-family:var(--f-mono);font-size:var(--t5);font-weight:600;
    font-variant-numeric:tabular-nums;color:var(--ink);margin-right:.4em;}
  .ff-scope .ff-fig.on b{color:var(--orange);}
  .ff-scope .ff-fig.on::before{content:"";display:inline-block;width:7px;height:7px;
    border-radius:50%;background:var(--orange);margin-right:.55em;vertical-align:.1em;
    animation:ff-pulse 2.4s ease-in-out infinite;}
  .ff-scope .ff-rail .note{margin-left:auto;font-family:var(--f-mono);font-size:var(--t1);
    color:var(--ink-3);letter-spacing:.04em;}

  /* ---- day heading: the spine of the list ---- */
  .ff-scope .ff-dayh{display:flex;align-items:baseline;gap:var(--s3);
    margin:var(--s6) 0 0;padding:0 0 var(--s2);border-bottom:1px solid var(--rule-2);}
  .ff-scope .ff-dayh .d{font-family:var(--f-display);font-size:var(--t6);font-weight:600;
    letter-spacing:-.018em;color:var(--ink);}
  .ff-scope .ff-dayh .dd{font-size:var(--t3);color:var(--ink-3);}
  .ff-scope .ff-dayh .c{margin-left:auto;font-family:var(--f-mono);font-size:var(--t2);
    color:var(--ink-3);font-variant-numeric:tabular-nums;}

  /* ---- a row, not a card ---- */
  .ff-scope .ff-list{list-style:none;margin:0;padding:0;}
  .ff-scope .ff-row{display:grid;grid-template-columns:var(--thumb) minmax(0,1fr);
    gap:var(--s4);padding:var(--s4) 0;border-top:1px solid var(--rule);list-style:none;}
  .ff-scope .ff-list>.ff-row:first-child{border-top:none;}

  /* The one place boldness is spent: something you could walk to right now. */
  .ff-scope .ff-row.is-live{border:1px solid var(--rule);border-left:3px solid var(--orange);
    border-radius:var(--r);background:var(--surface);box-shadow:var(--shadow);
    padding:var(--s4);margin:var(--s4) 0;}
  .ff-scope .ff-row.is-live+.ff-row{border-top:none;}

  .ff-scope .ff-body{min-width:0;}
  .ff-scope .ff-thumb{position:relative;width:var(--thumb);aspect-ratio:1;max-width:100%;
    border-radius:8px;overflow:hidden;background-color:var(--surface-2);
    background-size:cover;background-position:center;border:1px solid var(--rule);}
  .ff-scope .ff-thumb .fb{position:absolute;inset:0;display:grid;place-items:center;
    font-family:var(--f-display);font-size:var(--t4);font-weight:600;color:var(--ink-3);}
  /* The photo rides on an overlay above the initials rather than on an img
     element, so a dead Localist URL simply never paints and the typographic
     tile shows through -- no broken-image glyph, and no JavaScript. */
  .ff-scope .ff-thumb::after{content:"";position:absolute;inset:0;
    background-image:inherit;background-size:cover;background-position:center;}

  .ff-scope .ff-when{font-family:var(--f-mono);font-size:var(--t2);font-weight:500;
    font-variant-numeric:tabular-nums;color:var(--ink-2);
    display:flex;flex-wrap:wrap;align-items:center;gap:.55em;}
  .ff-scope .ff-row.is-today .ff-when{color:var(--ink);}
  .ff-scope .ff-live{color:var(--orange);font-weight:600;text-transform:uppercase;
    letter-spacing:.09em;font-size:var(--t1);display:inline-flex;align-items:center;gap:.45em;}
  .ff-scope .ff-live::before{content:"";width:6px;height:6px;border-radius:50%;
    background:var(--orange);animation:ff-pulse 2.4s ease-in-out infinite;}
  .ff-scope .ff-soon{color:var(--ink);font-weight:600;}

  .ff-scope .ff-head{display:flex;align-items:flex-start;justify-content:space-between;
    gap:var(--s3);margin-top:var(--s2);}
  .ff-scope .ff-title{font-family:var(--f-display);font-size:var(--t5);font-weight:600;
    line-height:1.28;letter-spacing:-.014em;margin:0;padding:0;text-wrap:balance;
    min-width:0;overflow-wrap:break-word;}
  .ff-scope .ff-row.is-live .ff-title{font-size:var(--t6);}
  .ff-scope .ff-title a{color:var(--ink);text-decoration:none;}
  .ff-scope .ff-title a:hover{color:var(--orange);text-decoration:underline;
    text-underline-offset:3px;}
  .ff-scope .ff-where{font-size:var(--t3);color:var(--ink-2);margin-top:var(--s1);
    overflow-wrap:break-word;}
  .ff-scope .ff-dept{font-size:var(--t2);color:var(--ink-3);margin-top:2px;
    overflow-wrap:break-word;}

  .ff-scope .ff-pill{flex:none;font-size:var(--t1);font-weight:700;text-transform:uppercase;
    letter-spacing:.07em;padding:.28em .62em;border-radius:999px;border:1px solid;
    white-space:nowrap;}
  .ff-scope .p-high{color:var(--high-fg);background:var(--high-bg);border-color:var(--high-br);}
  .ff-scope .p-med{color:var(--med-fg);background:var(--med-bg);border-color:var(--med-br);}
  .ff-scope .p-low{color:var(--low-fg);background:var(--low-bg);border-color:var(--low-br);}

  /* The matched sentence is the app's whole argument, so it is set as a
     citation rather than boxed up like a side note. */
  .ff-scope .ff-ev{margin:var(--s3) 0 0;padding:0 0 0 var(--s3);
    border-left:2px solid var(--rule-2);}
  .ff-scope .ff-ev figcaption{font-family:var(--f-mono);font-size:var(--t1);
    text-transform:uppercase;letter-spacing:.13em;color:var(--ink-3);margin-bottom:.35em;}
  .ff-scope .ff-ev blockquote{margin:0;padding:0;border:none;font-size:var(--t3);
    line-height:1.6;color:var(--ink-2);font-style:normal;}
  .ff-scope .ff-ev mark{background:var(--mark);color:var(--ink);padding:.05em .14em;
    border-radius:3px;font-weight:600;box-decoration-break:clone;
    -webkit-box-decoration-break:clone;}

  .ff-scope .ff-blocked{margin-top:var(--s2);font-size:var(--t2);color:var(--med-fg);}

  .ff-scope .ff-foot{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2) var(--s3);
    margin-top:var(--s3);font-size:var(--t3);color:var(--ink-2);}
  .ff-scope .ff-cta{display:inline-block;background:var(--orange);
    color:var(--on-orange) !important;font-weight:600;font-size:var(--t2);
    padding:.42em .9em;border-radius:7px;text-decoration:none;
    transition:background .15s ease,transform .15s ease;}
  .ff-scope .ff-cta:hover{background:var(--orange-deep);transform:translateY(-1px);}
  .ff-scope .ff-closed{font-style:italic;color:var(--ink-3);}
  .ff-scope .ff-walkin{color:var(--ink-3);}

  .ff-scope .ff-more{margin-top:var(--s3);}
  .ff-scope .ff-more summary{cursor:pointer;list-style:none;display:inline-flex;
    align-items:center;gap:.55em;font-family:var(--f-mono);font-size:var(--t1);
    text-transform:uppercase;letter-spacing:.11em;color:var(--ink-3);
    transition:color .15s ease;}
  .ff-scope .ff-more summary::-webkit-details-marker{display:none;}
  .ff-scope .ff-more summary::after{content:"";width:5px;height:5px;
    border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;
    transform:rotate(45deg) translateY(-1px);transition:transform .2s ease;}
  .ff-scope .ff-more[open] summary::after{transform:rotate(-135deg) translateY(1px);}
  .ff-scope .ff-more summary:hover{color:var(--orange);}
  .ff-scope .ff-more .body{margin-top:var(--s2);font-size:var(--t3);line-height:1.65;
    color:var(--ink-2);max-width:68ch;}
  .ff-scope .ff-more .body p{margin:0 0 .7em;}
  .ff-scope .ff-more .types{font-family:var(--f-mono);font-size:var(--t1);
    color:var(--ink-3);text-transform:uppercase;letter-spacing:.09em;}

  .ff-scope .ff-empty{border:1px dashed var(--rule-2);border-radius:var(--r);
    padding:var(--s7) var(--s4);text-align:center;}
  .ff-scope .ff-empty strong{display:block;font-family:var(--f-display);font-size:var(--t6);
    font-weight:600;color:var(--ink);margin-bottom:var(--s2);}
  .ff-scope .ff-empty p{font-size:var(--t3);line-height:1.6;color:var(--ink-2);
    margin:0 auto;max-width:44ch;}

  /* ---- skeleton, shown while the calendar is being read ---- */
  .ff-scope .ff-skel{display:grid;grid-template-columns:var(--thumb) minmax(0,1fr);
    gap:var(--s4);padding:var(--s4) 0;border-top:1px solid var(--rule);}
  .ff-scope .ff-skel:first-child{border-top:none;}
  .ff-scope .ff-sk{border-radius:6px;background-size:200% 100%;
    background-image:linear-gradient(90deg,var(--surface-2) 0%,var(--rule) 50%,var(--surface-2) 100%);
    animation:ff-shimmer 1.4s linear infinite;}
  .ff-scope .ff-sk.t{aspect-ratio:1;border-radius:8px;}
  .ff-scope .ff-sk.a{height:10px;width:30%;margin-bottom:10px;}
  .ff-scope .ff-sk.b{height:15px;width:72%;margin-bottom:10px;}
  .ff-scope .ff-sk.c{height:10px;width:48%;}

  .ff-scope a:focus-visible,.ff-scope summary:focus-visible{outline:2px solid var(--orange);
    outline-offset:3px;border-radius:4px;}

  @keyframes ff-pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
  @keyframes ff-shimmer{to{background-position:-200% 0}}

  @media (max-width:620px){
    .ff-scope{--thumb:48px;}
    .ff-scope .ff-mast h1{font-size:var(--t7);}
    .ff-scope .ff-row{gap:var(--s3);}
    /* `stretch`, not `flex-start`: a column flex item sized to flex-start takes
       its max-content width, which pushes the board wider than the phone and
       scrolls the page sideways. */
    .ff-scope .ff-head{flex-direction:column;align-items:stretch;gap:var(--s2);}
    .ff-scope .ff-head .ff-pill{align-self:flex-start;}
    .ff-scope .ff-rail .note{margin-left:0;width:100%;}
  }
  /* Scoped to our own elements on purpose: a global `*` reset would also
     freeze Streamlit's spinner mid-sweep, which reads as broken rather than
     calm. Streamlit honours the preference for its own chrome already. */
  @media (prefers-reduced-motion:reduce){
    .ff-scope,.ff-scope *,.ff-scope *::before,.ff-scope *::after{
      animation:none !important;transition:none !important;}
  }
"""

PILL_CLASS = {HIGH: "p-high", MEDIUM: "p-med", LOW: "p-low"}

QUICK_FILTERS = ["all", "live", "today", "walkin"]
QUICK_LABELS = {"all": "All", "live": "On now", "today": "Today", "walkin": "No sign-up"}


def _token_block(tokens: str) -> str:
    return ".ff-scope,:root{" + tokens + "}"


def stylesheet(theme: str | None) -> str:
    """Build the stylesheet for all three theme states.

    Streamlit reports the resolved theme through st.context.theme.type, but it
    documents that value as unreliable on the first run of a session and right
    after the user flips the theme menu -- and it can be None outright. Trusting
    it alone would paint light-mode text onto dark chrome until the next rerun,
    so the layers are:

      1. the complete light palette, unconditionally;
      2. a prefers-color-scheme override, which is correct for the viewer who
         never touched Streamlit's menu -- including on that unreliable first run;
      3. a pin to the resolved theme, last so it wins, but only once Streamlit
         actually knows it. That is what catches an explicit choice which
         contradicts the OS setting.
    """
    css = [
        _FONTS,
        _token_block(LIGHT_TOKENS),
        "@media (prefers-color-scheme:dark){" + _token_block(DARK_TOKENS) + "}",
    ]
    if theme == "dark":
        css.append(_token_block(DARK_TOKENS))
    elif theme == "light":
        css.append(_token_block(LIGHT_TOKENS))
    css.append(COMPONENTS)
    return "<style>" + "\n".join(css) + "</style>"


def active_theme() -> str | None:
    """'light', 'dark', or None when Streamlit cannot say yet."""
    try:
        resolved = getattr(st.context.theme, "type", None)
    except Exception:  # noqa: BLE001 - no browser context yet, or an older runtime
        return None
    return resolved if resolved in ("light", "dark") else None


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
    """Escape the sentence, then mark the matched phrase inside it."""
    safe = html.escape(sentence)
    if not phrase:
        return safe
    pattern = re.compile(re.escape(html.escape(phrase)), re.IGNORECASE)
    return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", safe, count=1)


def format_time(row: EventRow) -> str:
    if row.all_day:
        return "All day"
    start = row.starts_at.strftime("%I:%M %p").lstrip("0")
    if row.ends_at:
        return f"{start} – {row.ends_at.strftime('%I:%M %p').lstrip('0')}"
    return start


def initials(row: EventRow) -> str:
    """Two letters for the fallback tile, from whoever is hosting."""
    source = row.department if row.department not in ("", "—") else row.title
    words = [w for w in re.split(r"[^A-Za-z]+", source) if w]
    return "".join(w[0].upper() for w in words[:2]) or "SU"


def photo_class(row: EventRow) -> str:
    return f"ff-p-{row.event_id}-{row.instance_id}"


def photo_rule(row: EventRow) -> str:
    """One CSS rule carrying this row's photo, or '' if there isn't a safe one.

    The URL goes into a stylesheet rather than a style attribute, and anything
    that could break out of the url() -- quotes, parens, backslashes, angle
    brackets, semicolons, whitespace -- disqualifies it outright instead of
    being escaped. Localist serves plain https CDN links, so nothing real is lost.
    """
    url = (row.photo_url or "").strip()
    if not url.startswith("https://") or re.search(r"""[\s'"()\\<>;]""", url):
        return ""
    return ".{}{{background-image:url('{}');}}".format(photo_class(row), url)


def thumb_html(row: EventRow) -> str:
    classes = "ff-thumb"
    if photo_rule(row):
        classes += " " + photo_class(row)
    return ('<span class="{}"><span class="fb">{}</span></span>'
            .format(classes, html.escape(initials(row))))


def when_html(row: EventRow, now: datetime) -> str:
    state = row.status(now)
    countdown = row.countdown(now)
    bits = []
    if state == LIVE:
        bits.append('<span class="ff-live">{}</span>'.format(
            html.escape(countdown or "on now")))
    bits.append("<span>{}</span>".format(html.escape(format_time(row))))
    if state == SOON and countdown:
        bits.append('<span class="ff-soon">{}</span>'.format(html.escape(countdown)))
    return '<div class="ff-when">' + "".join(bits) + "</div>"


def description_html(row: EventRow) -> str:
    text = (row.description_text or "").strip()
    if not text:
        return "<p>No description provided.</p>"
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return "".join("<p>{}</p>".format(html.escape(p)) for p in paragraphs)


def render_row(row: EventRow, now: datetime, today: date) -> str:
    state = row.status(now)
    classes = ["ff-row"]
    if state == LIVE:
        classes.append("is-live")
    if row.is_today(today):
        classes.append("is-today")

    pill = PILL_CLASS.get(row.food.confidence, "p-low")
    bits = [
        '<li class="{}">'.format(" ".join(classes)),
        thumb_html(row),
        '<div class="ff-body">',
        when_html(row, now),
        '<div class="ff-head">',
        # A div carrying role=heading, not an <h3>: Streamlit wraps markdown
        # headings in [data-testid="stHeadingWithActionElements"] and styles
        # them at a specificity no sane class selector can outrank. The ARIA
        # role keeps the outline intact for screen readers.
        '<div class="ff-title" role="heading" aria-level="3">'
        '<a href="{}" target="_blank" rel="noopener">{}</a></div>'.format(
            html.escape(row.event_url), html.escape(row.title)),
        '<span class="ff-pill {}">{}</span>'.format(
            pill, html.escape(row.food.confidence or "Low")),
        "</div>",
        '<div class="ff-where">{}</div>'.format(html.escape(row.location_full)),
        '<div class="ff-dept">{}</div>'.format(html.escape(row.department)),
    ]

    match = row.food.best_match
    if match:
        bits.append(
            '<figure class="ff-ev"><figcaption>Food mention</figcaption>'
            "<blockquote>{}</blockquote></figure>".format(
                highlight(match.sentence, match.phrase)))

    if row.food.blocked_by:
        bits.append('<div class="ff-blocked">This listing says food is not provided.</div>')

    reg = row.registration
    if reg.show_signup_badge:
        bits.append(
            '<div class="ff-foot"><span>Registration required</span>'
            '<a class="ff-cta" href="{}" target="_blank" rel="noopener">Sign up</a></div>'
            .format(html.escape(reg.url or row.event_url)))
    elif reg.required:
        bits.append('<div class="ff-foot"><span class="ff-closed">'
                    "Registration closed — walk-ins may be accommodated.</span></div>")
    else:
        bits.append('<div class="ff-foot"><span class="ff-walkin">'
                    "No registration needed — just show up.</span></div>")

    bits.append(
        '<details class="ff-more"><summary>Full description</summary>'
        '<div class="body">{}</div><div class="types">Event types: {}</div></details>'.format(
            description_html(row),
            html.escape(", ".join(row.event_types) or "—")))
    bits.append("</div></li>")
    return "".join(bits)


def render_results(visible: list[EventRow], now: datetime, today: date) -> str:
    """The whole board as one HTML string, so nothing depends on Streamlit's
    own vertical spacing between blocks."""
    out: list[str] = []
    current_day = None
    for row in visible:
        if row.start_date != current_day:
            if current_day is not None:
                out.append("</ol>")
            current_day = row.start_date
            full = current_day.strftime("%A, %B %d").replace(" 0", " ")
            if current_day == today:
                lead = "Today"
            elif current_day == today + timedelta(days=1):
                lead = "Tomorrow"
            else:
                lead = full.split(",", 1)[0]
            count = sum(1 for r in visible if r.start_date == current_day)
            out.append(
                '<div class="ff-dayh" role="heading" aria-level="2">'
                '<span class="d">{}</span><span class="dd">{}</span>'
                '<span class="c">{}</span></div><ol class="ff-list">'.format(
                    html.escape(lead), html.escape(full),
                    "{} event{}".format(count, "s" if count != 1 else "")))
        out.append(render_row(row, now, today))
    if current_day is not None:
        out.append("</ol>")
    rules = "".join(r for r in (photo_rule(row) for row in visible) if r)
    style = f"<style>{rules}</style>" if rules else ""
    return '<div class="ff-scope">' + style + "".join(out) + "</div>"


SKELETON = (
    '<div class="ff-scope">'
    + ''.join(
        '<div class="ff-skel"><div class="ff-sk t"></div><div>'
        '<div class="ff-sk a"></div><div class="ff-sk b"></div><div class="ff-sk c"></div>'
        "</div></div>"
        for _ in range(4))
    + "</div>"
)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = get_config()
    st.set_page_config(page_title=cfg.ui.page_title, page_icon="\U0001F355", layout="wide")
    st.markdown(stylesheet(active_theme()), unsafe_allow_html=True)

    if "bust" not in st.session_state:
        st.session_state.bust = 0
    # Set by the Refresh button and consumed by the very next load_rows call.
    # It must not persist: a sticky flag would re-scrape the live calendar on
    # every later rerun, including a slider nudge or a local config.yaml edit.
    if "force_next" not in st.session_state:
        st.session_state.force_next = False

    # -- sidebar, part one ------------------------------------------------
    with st.sidebar:
        st.markdown("### Filters")
        window_days = st.slider("Look ahead (days)", 1, 30, cfg.fetch.window_days,
                                help="How far into the future to search.")

        if st.button("↻ Refresh from events.syracuse.edu", use_container_width=True):
            st.session_state.bust += 1
            st.session_state.force_next = True
            load_rows.clear()
            st.rerun()

    # Read-and-clear, so `force` is true for this run only.
    force = st.session_state.force_next
    st.session_state.force_next = False

    st.markdown(
        '<div class="ff-scope"><header class="ff-mast">'
        '<div class="ff-eyebrow">Syracuse University</div>'
        "<h1>Free Food Finder</h1>"
        '<p class="ff-lede">Events serving food in the next {} days. '
        "Every match shows the sentence it came from, so you can judge it "
        "yourself.</p></header></div>".format(window_days),
        unsafe_allow_html=True)

    slot = st.empty()
    slot.markdown(SKELETON, unsafe_allow_html=True)
    try:
        rows, meta = load_rows(window_days, force, st.session_state.bust,
                               current_config_mtime())
    except Exception as exc:  # noqa: BLE001 - surfaced to the user below
        slot.empty()
        st.error(f"Could not load events: {exc}")
        st.stop()
    slot.empty()

    today = date.today()
    now = datetime.now().astimezone()   # aware: EventRow timestamps carry offsets

    # -- sidebar, part two: filters built from the data we actually have ---
    with st.sidebar:
        confidences = st.multiselect(
            "Confidence", CONFIDENCE_LEVELS, default=list(cfg.ui.default_confidences),
            key="confidences",
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

    # -- sidebar filters --------------------------------------------------
    scoped = [r for r in rows if r.food.confidence in confidences]
    if only_today:
        scoped = [r for r in scoped if r.is_today(today)]
    if reg_choice == "Required":
        scoped = [r for r in scoped if r.registration.required]
    elif reg_choice == "Not required":
        scoped = [r for r in scoped if not r.registration.required]
    if chosen_locations:
        scoped = [r for r in scoped if r.location in chosen_locations]
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        start, end = date_range
        scoped = [r for r in scoped if start <= r.start_date <= end]

    # -- search + quick filters, in the column where they get used --------
    counts = {
        "all": len(scoped),
        "live": sum(1 for r in scoped if r.status(now) in (LIVE, SOON)),
        "today": sum(1 for r in scoped if r.is_today(today)),
        "walkin": sum(1 for r in scoped if not r.registration.required),
    }
    left, right = st.columns([5, 6], vertical_alignment="center")
    with left:
        query = st.text_input("Search", placeholder="Search events, places, food…",
                              label_visibility="collapsed")
    with right:
        quick = st.pills("Quick filter", QUICK_FILTERS, default="all",
                         selection_mode="single", label_visibility="collapsed",
                         format_func=lambda k: f"{QUICK_LABELS[k]} · {counts[k]}")

    visible = list(scoped)
    if query and query.strip():
        q = query.strip().lower()
        visible = [r for r in visible
                   if q in r.title.lower() or q in r.location_full.lower()
                   or q in r.department.lower() or q in r.description_text.lower()]
    if quick == "live":
        visible = [r for r in visible if r.status(now) in (LIVE, SOON)]
    elif quick == "today":
        visible = [r for r in visible if r.is_today(today)]
    elif quick == "walkin":
        visible = [r for r in visible if not r.registration.required]

    # -- summary rail -----------------------------------------------------
    live_count = sum(1 for r in visible if r.status(now) == LIVE)
    today_count = sum(1 for r in visible if r.is_today(today))
    updated = meta["fetched_at"].strftime("%I:%M %p").lstrip("0")
    st.markdown(
        '<div class="ff-scope"><div class="ff-rail">'
        '<span class="ff-fig{}"><b>{}</b> on now</span>'
        '<span class="ff-fig"><b>{}</b> today</span>'
        '<span class="ff-fig"><b>{}</b> shown</span>'
        '<span class="note">Updated {}</span>'
        "</div></div>".format(
            " on" if live_count else "", live_count, today_count,
            len(visible), html.escape(updated)),
        unsafe_allow_html=True)

    if not visible:
        missing = [c for c in CONFIDENCE_LEVELS if c not in confidences]
        st.markdown(
            '<div class="ff-scope"><div class="ff-empty">'
            "<strong>Nothing matches yet.</strong>"
            "<p>Widen the date range, clear the search box, or let a weaker "
            "food mention through.</p></div></div>",
            unsafe_allow_html=True)
        if missing:
            _, mid, _ = st.columns([1, 2, 1])
            with mid:
                if st.button("Include {}-confidence matches".format(missing[-1].lower()),
                             use_container_width=True):
                    st.session_state.confidences = CONFIDENCE_LEVELS
                    st.rerun()
        return

    st.markdown(render_results(visible, now, today), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
