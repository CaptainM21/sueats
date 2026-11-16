"""Polite HTTP client for the Localist API.

Honors events.syracuse.edu/robots.txt (which sets Crawl-Delay: 1), sends a
descriptive User-Agent, and caches every response on disk so repeated runs
and reruns of the dashboard do not re-hit the server.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .config import Config, PROJECT_ROOT

log = logging.getLogger(__name__)
CACHE_DIR = PROJECT_ROOT / ".cache"


class RobotsDisallowed(RuntimeError):
    """Raised when robots.txt forbids a URL we were about to request."""


@dataclass
class FetchStats:
    requests_made: int = 0
    cache_hits: int = 0
    pages: int = 0
    fetched_at: datetime | None = None


class PoliteSession:
    """A requests session with a hard minimum delay between network calls."""

    def __init__(self, cfg: Config, cache_dir: Path = CACHE_DIR):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = FetchStats()
        self._last_request = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": cfg.source.user_agent,
            "Accept": "application/json, text/html;q=0.9",
        })

    # -- robots -----------------------------------------------------------

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        if root not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(urljoin(root, "/robots.txt"))
            try:
                self._throttle()
                resp = self.session.get(urljoin(root, "/robots.txt"), timeout=15)
                parser.parse(resp.text.splitlines())
                self.stats.requests_made += 1
            except requests.RequestException as exc:
                log.warning("Could not read robots.txt for %s (%s); assuming allowed", root, exc)
                parser.parse([])
            self._robots[root] = parser
        return self._robots[root]

    def allowed(self, url: str) -> bool:
        if not self.cfg.fetch.respect_robots:
            return True
        return self._robots_for(url).can_fetch(self.cfg.source.user_agent, url)

    # -- rate limiting ----------------------------------------------------

    def _throttle(self) -> None:
        """Block until at least rate_limit_seconds has passed since the last call."""
        wait = self.cfg.fetch.rate_limit_seconds - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    # -- caching ----------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.json"

    def _read_cache(self, url: str):
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            age = datetime.now(timezone.utc) - datetime.fromisoformat(blob["fetched_at"])
            if age > timedelta(minutes=self.cfg.fetch.cache_ttl_minutes):
                return None
            return blob["body"]
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def _write_cache(self, url: str, body) -> None:
        self._cache_path(url).write_text(
            json.dumps({"url": url,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "body": body}),
            encoding="utf-8")

    def clear_cache(self) -> int:
        removed = 0
        for path in self.cache_dir.glob("*.json"):
            path.unlink()
            removed += 1
        return removed

    # -- requests ---------------------------------------------------------

    def get_json(self, url: str, use_cache: bool = True):
        if use_cache:
            cached = self._read_cache(url)
            if cached is not None:
                self.stats.cache_hits += 1
                return cached

        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        last_error = None
        for attempt in range(self.cfg.fetch.max_retries):
            self._throttle()
            try:
                resp = self.session.get(url, timeout=self.cfg.fetch.timeout_seconds)
                self.stats.requests_made += 1
                if resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}"
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                body = resp.json()
                self._write_cache(url, body)
                return body
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(2 ** attempt)

        raise RuntimeError(f"Failed to fetch {url} after "
                           f"{self.cfg.fetch.max_retries} attempts: {last_error}")


def fetch_events(cfg: Config, session: PoliteSession | None = None,
                 window_days: int | None = None, force_refresh: bool = False):
    """Pull every event in the window, following Localist's pagination.

    Returns (raw_event_dicts, stats). The API returns one entry per *instance*,
    so the same event appears repeatedly; de-duplication happens in normalize.
    """
    session = session or PoliteSession(cfg)
    days = window_days or cfg.fetch.window_days
    collected, page = [], 1

    while True:
        url = (f"{cfg.source.api_base}?days={days}"
               f"&pp={cfg.fetch.page_size}&page={page}")
        payload = session.get_json(url, use_cache=not force_refresh)
        collected.extend(item["event"] for item in payload.get("events", []))

        info = payload.get("page", {})
        session.stats.pages = page
        if not info.get("next_page") or page >= info.get("total", page):
            break
        page += 1

    session.stats.fetched_at = datetime.now(timezone.utc)
    return collected, session.stats
