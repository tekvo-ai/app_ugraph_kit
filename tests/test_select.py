"""Selection semantics shared by every command that walks the KB.

The module docstring names the bug these tests exist to prevent: sorting
["2026-08-02", "2026-07-31", None] descending with a naive key puts the *undated*
page first, so `--newest 3` confidently returns pages whose date nobody knows.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from ugraph import select


def page(slug, published=None):
    """A Page-shaped item: selection fields live in .meta."""
    return SimpleNamespace(meta={"slug": slug, "published": published}, id=slug)


def item(slug, published=None):
    """A ledger.Item-shaped item: selection fields are plain attributes."""
    return SimpleNamespace(slug=slug, published=published)


# --- parse_since ------------------------------------------------------------

def test_parse_since_reads_an_iso_date():
    assert select.parse_since("2026-07-25") == date(2026, 7, 25)


@pytest.mark.parametrize("text,days", [("7d", 7), ("2w", 14), ("3m", 90), ("1y", 365)])
def test_parse_since_reads_relative_windows(text, days):
    today = date(2026, 8, 1)
    assert (today - select.parse_since(text, today=today)).days == days


def test_parse_since_is_case_insensitive():
    today = date(2026, 8, 1)
    assert select.parse_since("2W", today=today) == select.parse_since("2w", today=today)


def test_parse_since_rejects_nonsense_with_the_accepted_forms():
    with pytest.raises(ValueError) as exc:
        select.parse_since("last tuesday")
    assert "YYYY-MM-DD" in str(exc.value)


# --- the ordering trap ------------------------------------------------------

def test_undated_pages_sort_last_not_first():
    pages = [page("a", None), page("b", "2026-08-02"), page("c", "2026-07-31")]
    assert [p.meta["slug"] for p in select.newest_first(pages)] == ["b", "c", "a"]


def test_newest_n_never_returns_an_undated_page_ahead_of_a_dated_one():
    pages = [page("undated-1"), page("undated-2"),
             page("recent", "2026-08-02"), page("older", "2026-01-01")]
    top2 = select.by_recency(pages, newest=2)
    assert [p.meta["slug"] for p in top2] == ["recent", "older"]


def test_since_drops_undated_pages():
    pages = [page("undated"), page("recent", "2026-08-02")]
    kept = select.by_recency(pages, since=date(2026, 1, 1))
    assert [p.meta["slug"] for p in kept] == ["recent"]


def test_same_day_pages_tie_break_on_slug_ascending():
    pages = [page("zulu", "2026-08-02"), page("alpha", "2026-08-02")]
    assert [p.meta["slug"] for p in select.newest_first(pages)] == ["alpha", "zulu"]


def test_ordering_is_stable_across_runs():
    pages = [page("b", "2026-08-02"), page("a", "2026-08-02"), page("c", None)]
    once = [p.meta["slug"] for p in select.newest_first(pages)]
    twice = [p.meta["slug"] for p in select.newest_first(list(reversed(pages)))]
    assert once == twice


# --- field access across both item shapes -----------------------------------

def test_selection_reads_page_shaped_and_item_shaped_alike():
    assert select.published(page("x", "2026-08-02")) == "2026-08-02"
    assert select.published(item("x", "2026-08-02")) == "2026-08-02"
    assert select.is_dated(page("x")) is False
    assert select.is_dated(item("x")) is False


def test_channel_is_the_first_slug_segment_not_the_frontmatter_field():
    p = SimpleNamespace(meta={"slug": "ai-engineer/some-talk",
                              "channel": "AI Engineer"}, id="x")
    assert select.channel_of(p) == "ai-engineer"


def test_a_slug_with_no_segment_has_no_channel():
    assert select.channel_of(page("standalone")) == ""


# --- combination ------------------------------------------------------------

def test_filters_apply_channel_then_since_then_newest():
    pages = [
        page("ai-engineer/new", "2026-08-02"),
        page("ai-engineer/old", "2020-01-01"),
        page("other/new", "2026-08-03"),
    ]
    got = select.by_recency(pages, newest=1, since=date(2026, 1, 1),
                            channel="ai-engineer")
    assert [p.meta["slug"] for p in got] == ["ai-engineer/new"]


def test_no_filters_returns_everything_ordered():
    pages = [page("a", "2026-01-01"), page("b", "2026-08-02")]
    assert len(select.by_recency(pages)) == 2


def test_by_recency_does_not_mutate_the_input():
    pages = [page("a", "2026-01-01"), page("b", "2026-08-02")]
    original = list(pages)
    select.by_recency(pages, newest=1)
    assert pages == original


def test_describe_reads_as_a_phrase():
    assert select.describe(newest=5) == "5 most recent"
    assert select.describe(since=date(2026, 1, 1)) == "published since 2026-01-01"
    assert select.describe(newest=5, since=date(2026, 1, 1), channel="ai-engineer") == (
        "5 most recent, published since 2026-01-01, in ai-engineer")
    assert select.describe() == ""
