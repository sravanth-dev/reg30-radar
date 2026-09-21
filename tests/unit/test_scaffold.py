"""Scaffold smoke tests.

These use the standard library only, so the test harness can be verified before the
dependency set has been proven on this Python version (Slice 0, Step 1).
"""

import tomllib
from pathlib import Path

import tradebot

ROOT = Path(__file__).resolve().parents[2]


def test_package_imports():
    assert tradebot.__version__


def test_layout_matches_architecture():
    # ARCHITECTURE.md Sect.9 names these directories; later slices reference them by name,
    # so a missing one should fail here rather than halfway through a backfill.
    for name in ("config", "prompts", "migrations", "reports", "spikes", "tests/fixtures"):
        assert (ROOT / name).is_dir(), f"missing directory: {name}"


def test_dependencies_are_the_approved_list():
    # Adding a dependency is a decision Sravanth makes, not a side effect of a commit
    # (CLAUDE.md, "Ask before"). This pins the list so a stray addition fails the build.
    approved = {
        "requests", "feedparser", "pdfplumber", "pypdf", "lxml",
        "psycopg[binary]", "pydantic", "openai", "APScheduler",
        "python-dotenv", "PyYAML",
    }
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(declared["project"]["dependencies"]) == approved


def test_env_example_has_no_real_secret():
    # .env.example is committed; it must never carry a usable value.
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(("OPENAI_API_KEY", "DATABASE_URL")):
            assert "CHANGEME" in line, f"looks like a real value: {line.split('=')[0]}"
