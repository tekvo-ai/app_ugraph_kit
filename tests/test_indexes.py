"""Index generation is deterministic by contract.

`check()` and `write_all()` must agree exactly — that equivalence is what lets
`ugraph index --check` gate CI without a fresh checkout diverging from the
committed one. It is a byte comparison, so "nearly identical" is a failure.
"""

from __future__ import annotations

from conftest import concept, entity

from ugraph import indexes


def test_build_all_is_pure(populated):
    before = {p for p in populated.kb.rglob("*.md")}
    indexes.build_all(populated)
    assert {p for p in populated.kb.rglob("*.md")} == before


def test_build_all_is_deterministic(populated):
    first = indexes.build_all(populated)
    second = indexes.build_all(populated)
    assert first == second


def test_write_all_creates_the_indexes(populated):
    written = indexes.write_all(populated)
    assert written
    assert (populated.kb / "index.md").is_file()
    assert (populated.kb / "concepts" / "index.md").is_file()
    assert (populated.kb / "sources" / "index.md").is_file()


def test_write_all_is_idempotent(populated):
    indexes.write_all(populated)
    assert indexes.write_all(populated) == []


def test_write_all_does_not_touch_unchanged_files(populated):
    indexes.write_all(populated)
    root = populated.kb / "index.md"
    before = root.stat().st_mtime_ns
    indexes.write_all(populated)
    assert root.stat().st_mtime_ns == before


def test_check_is_empty_exactly_when_write_all_would_be_a_noop(populated):
    assert indexes.check(populated)          # nothing written yet
    indexes.write_all(populated)
    assert indexes.check(populated) == []


def test_check_writes_nothing(populated):
    indexes.write_all(populated)
    (populated.kb / "index.md").write_text("tampered\n", encoding="utf-8")
    stale = indexes.check(populated)
    assert (populated.kb / "index.md") in stale
    # check() reports, it does not repair
    assert (populated.kb / "index.md").read_text() == "tampered\n"


def test_a_new_page_makes_its_index_stale(populated):
    indexes.write_all(populated)
    concept(populated, "late-arrival")
    stale = indexes.check(populated)
    assert (populated.kb / "concepts" / "index.md") in stale


def test_new_concept_appears_in_the_concepts_index(populated):
    concept(populated, "late-arrival", title="Late Arrival")
    indexes.write_all(populated)
    assert "Late Arrival" in (populated.kb / "concepts" / "index.md").read_text()


def test_entities_are_indexed_under_their_subtype(populated):
    entity(populated, "ada-lovelace", subtype="person")
    indexes.write_all(populated)
    people = populated.kb / "entities" / "people" / "index.md"
    assert people.is_file()
    assert "Ada Lovelace" in people.read_text()


def test_every_index_ends_with_a_single_newline(populated):
    for path, content in indexes.build_all(populated):
        assert content.endswith("\n"), path
        assert not content.endswith("\n\n"), path


def test_indexes_are_stable_across_page_write_order(tmp_path):
    """Two KBs with the same pages written in opposite order render identically."""
    from conftest import scaffold

    a = scaffold(tmp_path / "a")
    b = scaffold(tmp_path / "b")
    for slug in ("alpha", "beta", "gamma"):
        concept(a, slug)
    for slug in ("gamma", "beta", "alpha"):
        concept(b, slug)
    rendered_a = [content for _p, content in indexes.build_all(a)]
    rendered_b = [content for _p, content in indexes.build_all(b)]
    assert rendered_a == rendered_b
