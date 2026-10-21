"""The order-relevance gate: decides which filings get a PDF download, and, of those,
which are allowed anywhere near the LLM (ARCHITECTURE.md §5.4).

This is deliberately narrower than the full router (noise / other_material / results /
red_flag / catch_all / order_candidate / order_win) that §5.4 describes and Slice 3 will
build. It only tells apart what `src/reg30_radar/orders/` needs for this run: which of
§5.4's already-decided category rules apply, and the keyword prefilter that decides
whether a `catch_all` filing is worth a look.

**`llm_allowed` is the single choke point.** Nothing in `src/reg30_radar/orders/` may hand a
`maybe_transcribe` or `LlmClient` call to a filing without going through it first - not
"usually doesn't", structurally can't, because `run.py` reads `relevance.order_related`
before it will pass anything but `ocr=None` into `documents.pipeline.process_url`. A
`red_flag` filing (the word "order" in the category name notwithstanding) and an
out-of-scope category are always `order_related=False` and can never flip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from reg30_radar.common.config import category_map as category_map_config

# §5.3's category normalisation: a trailing "-XBRL" and a "(Sub-para ...)" suffix don't
# change what a filing is about, so both are stripped before the bucket lookup.
_XBRL_SUFFIX = re.compile(r"-XBRL\s*$", re.I)
_PARA_SUFFIX = re.compile(r"\s*\(Sub-para[^)]*\)\s*$", re.I)


def normalize_category(raw: str | None) -> str:
    if not raw:
        return ""
    s = _XBRL_SUFFIX.sub("", raw.strip())
    s = _PARA_SUFFIX.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


@cache
def _bucket_lookup() -> dict[str, str]:
    """casefolded category string -> bucket, built once from config/category_map.yaml.
    Case-insensitive because NSE writes the same category both ways ("General Updates"
    and "General updates" both appear in the live feed)."""
    cfg = category_map_config()
    out: dict[str, str] = {}
    for bucket, categories in cfg.items():
        for category in categories:
            out[category.casefold()] = bucket
    return out


def bucket_of(category_raw: str | None) -> str:
    """The category map's bucket for any filing (§5.4), or "unknown" for a category the
    map does not list. The event study treats unknown as other news near an order, the
    cautious direction, and logs it to `unknown_categories` for review."""
    return _bucket_lookup().get(normalize_category(category_raw).casefold(), "unknown")


# §5.4's keyword prefilter. On the headline, both lists apply; on extracted body text,
# only the positive list, and only strong phrases - bare "order"/"contract" would flag
# "in order to" in half the filings on any given day, and a body-text false positive from
# a stronger phrase costs a fraction of a cent, while a false negative loses an order.
_HEADLINE_POSITIVE = re.compile(
    r"\border\b|\bcontract\b|\baward(?:ed|ing)?\b|letter of award|\bLo[AI]\b|"
    r"letter of intent|work order|purchase order|\bL[- ]?1\b|lowest bidder", re.I)
_HEADLINE_SUPPRESS = re.compile(
    r"orders?\s+passed|income tax|assessment|\bNCLT\b|\bcourt\b|\btribunal\b", re.I)

_BODY_POSITIVE = re.compile(
    r"work order|purchase order|letter of award|letter of intent|\bLo[AI]\b|\bL[- ]?1\b|"
    r"lowest bidder|orders?\s+(?:worth|valued at|amounting to)|"
    r"\b(?:bagged|secured|received|won|awarded with)\b[^.\n]{0,40}\b(?:order|contract)s?\b",
    re.I,
)


@dataclass(frozen=True)
class Relevance:
    bucket: str            # "order_win" | "order_candidate" | "red_flag" | "catch_all" |
                            # "out_of_scope"
    order_related: bool    # the one field llm_allowed reads
    reason: str


UNKNOWN_PREFIX = "unknown category"


def log_unknown(conn, category: str | None, seen_at) -> None:
    """One row per category the map does not list, counted per filing, for review
    (§5.4). Callers log a filing once, when it is first processed."""
    conn.execute("insert into unknown_categories (category_raw, first_seen, count)"
                 " values (%s, %s, 1) on conflict (category_raw) do update set"
                 " count = unknown_categories.count + 1", (category or "", seen_at))


def classify(category_raw: str | None, headline: str | None) -> Relevance:
    """Decide relevance before any PDF is downloaded, from category and headline alone -
    this is what decides whether OCR is offered to a page that turns out unreadable
    (§5.5: OCR has to be decided before download, so the PDF still exists to render).
    """
    category = normalize_category(category_raw)
    bucket = _bucket_lookup().get(category.casefold())
    prefix = ""
    if bucket is None:
        # §5.4: an unknown category is catch_all, the safe default, so an order filed
        # under a category NSE adds later is still read (Proposed, 20 Oct 2026; before,
        # it was out of scope and never logged on the live path).
        bucket, prefix = "catch_all", f"{UNKNOWN_PREFIX} {category!r}; "

    if bucket in ("order_win", "order_candidate"):
        return Relevance(bucket, True, f"category is {bucket} ({category!r})")

    if bucket == "red_flag":
        # The word "order" in the category name is misleading (§5.4) - never an order win.
        return Relevance(bucket, False, f"red_flag category ({category!r}); never an order")

    if bucket == "catch_all":
        headline = headline or ""
        if _HEADLINE_SUPPRESS.search(headline):
            return Relevance(bucket, False, prefix + "catch_all; headline matches a suppress term")
        m = _HEADLINE_POSITIVE.search(headline)
        if m:
            return Relevance(bucket, True, prefix + f"catch_all; headline keyword {m.group(0)!r}")
        return Relevance(bucket, False, prefix + "catch_all; no headline keyword match")

    return Relevance("out_of_scope", False, f"category {category!r} not in this run's scope")


def refine_with_body(relevance: Relevance, body_text: str | None) -> Relevance:
    """After extraction, give a `catch_all` filing with no headline hit a second look at
    its body text (§5.4: HILINFRA's real order win arrived as a plain Press Release with a
    generic headline). Never touches anything already decided, and never runs OCR - by the
    time this is called, D8 may already have deleted the PDF, so the only text available is
    whatever T0 extraction produced.
    """
    if relevance.bucket != "catch_all" or relevance.order_related:
        return relevance
    m = _BODY_POSITIVE.search(body_text or "")
    if m:
        return Relevance(relevance.bucket, True, f"catch_all; body keyword {m.group(0)!r}")
    return relevance


def llm_allowed(relevance: Relevance) -> bool:
    """The single gate. True for order_win, order_candidate, and a catch_all filing that
    the keyword prefilter (headline or, after extraction, body) has flagged. False for
    everything else, red_flag included.
    """
    return relevance.order_related


def in_scope(relevance: Relevance) -> bool:
    """Whether this filing's PDF gets downloaded at all in this run (widened D7: order_win,
    order_candidate and every catch_all, not only LLM-confirmed catch_all - see WORKLOG,
    24 Sep 2026 night, continued).
    """
    return relevance.bucket in ("order_win", "order_candidate", "catch_all")
