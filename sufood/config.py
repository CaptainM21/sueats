"""Loads config.yaml into validated, pre-compiled settings objects."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _compile_all(patterns: list[str], label: str) -> list[re.Pattern]:
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(f"config.yaml: bad regex in {label}: {p!r} ({exc})") from exc
    return compiled


@dataclass
class SourceConfig:
    api_base: str
    site_base: str
    user_agent: str


@dataclass
class FetchConfig:
    window_days: int
    rate_limit_seconds: float
    cache_ttl_minutes: int
    page_size: int
    timeout_seconds: int
    max_retries: int
    respect_robots: bool
    fetch_event_pages: bool


@dataclass
class DetectionConfig:
    strong_signals: list[re.Pattern]
    weak_signals: list[re.Pattern]
    weak_modifiers: list[re.Pattern]
    masking_phrases: list[re.Pattern]
    blocking_phrases: list[re.Pattern]
    restricted_event_types: set[str]
    ongoing_span_days: int


@dataclass
class RegistrationConfig:
    signals: list[re.Pattern]
    ignore: list[re.Pattern]
    closed_phrases: list[re.Pattern]


@dataclass
class UIConfig:
    default_confidences: list[str]
    page_title: str


@dataclass
class Config:
    source: SourceConfig
    fetch: FetchConfig
    detection: DetectionConfig
    registration: RegistrationConfig
    ui: UIConfig
    raw: dict = field(repr=False, default_factory=dict)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    d, r = raw["detection"], raw["registration"]
    return Config(
        source=SourceConfig(**raw["source"]),
        fetch=FetchConfig(**raw["fetch"]),
        detection=DetectionConfig(
            strong_signals=_compile_all(d["strong_signals"], "strong_signals"),
            weak_signals=_compile_all(d["weak_signals"], "weak_signals"),
            weak_modifiers=_compile_all(d["weak_modifiers"], "weak_modifiers"),
            masking_phrases=_compile_all(d["masking_phrases"], "masking_phrases"),
            blocking_phrases=_compile_all(d["blocking_phrases"], "blocking_phrases"),
            restricted_event_types=set(d["restricted_event_types"]),
            ongoing_span_days=int(d["ongoing_span_days"]),
        ),
        registration=RegistrationConfig(
            signals=_compile_all(r["signals"], "registration.signals"),
            ignore=_compile_all([re.escape(x) for x in r["ignore"]], "registration.ignore"),
            closed_phrases=_compile_all(r["closed_phrases"], "registration.closed_phrases"),
        ),
        ui=UIConfig(**raw["ui"]),
        raw=raw,
    )


@lru_cache(maxsize=4)
def get_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """Cached loader for app use; tests call load_config() directly."""
    return load_config(path)
