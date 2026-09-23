"""Where configuration comes from, and nowhere else.

Two sources, with a clean split:

- `config/*.yaml` holds everything about the outside world - endpoints, headers,
  parameters, pacing, the trading calendar. The scraping rules in CLAUDE.md put these in
  config precisely so a URL is never buried in code.
- `.env` holds only secrets and machine-local settings. It is never committed.

The User-Agent lives in `config/sources.yaml`, not `.env`. It is not a secret, it is part
of how we identify ourselves to NSE, and D25 requires it to be one consistent string that
is never rotated - which is easier to honour when there is exactly one place to look.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "config"


@cache
def _load_env_once() -> None:
    load_dotenv(ROOT / ".env")


def env(name: str, *, required: bool = True) -> str | None:
    """Read one variable from the environment, having loaded `.env` first.

    Fails loudly when a required variable is missing or still holds the placeholder from
    `.env.example`. A collector that starts with a placeholder password only discovers it
    at the first write, by which point it has already made requests to NSE.
    """
    _load_env_once()
    value = os.environ.get(name)
    if required and (not value or value == "CHANGEME"):
        raise RuntimeError(
            f"{name} is missing or still set to CHANGEME in {ROOT / '.env'}. "
            f"See .env.example for what it should hold."
        )
    return value


@cache
def load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"missing config file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def sources() -> dict:
    return load_yaml("sources.yaml")


def nse() -> dict:
    return sources()["nse"]


def database_url() -> str:
    return env("DATABASE_URL")
