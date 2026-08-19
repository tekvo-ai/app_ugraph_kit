"""lint is documented as a CI gate — it exits non-zero, so its verdicts are API.

These tests pin which conditions are *errors* (block) versus *warnings* (report),
because a check that silently downgrades to a warning is a gate that fails open.
"""

from __future__ import annotations

from conftest import TODAY, concept, page, source

from ugraph import indexes, lint


def checks(findings_list) -> set[str]:
    return {f["check"] for f in findings_list}


def messages(findings_list) -> str:
    return " | ".join(f["message"] for f in findings_list)


def test_clean_kb_has_no_findings(populated):
    indexes.write_all(populated)
    f, pages = lint.lint(populated)
    assert [p.id for p in pages]
    assert f.errors == []
    assert f.warnings == []
    assert f.total == 0


def test_lint_returns_every_page_it_loaded(populated):
    indexes.write_all(populated)
    _f, pages = lint.lint(populated)
    ids = {p.id for p in pages}
    assert "concepts/hybrid-retrieval" in ids
    assert "entities/tools/ugraph" in ids
    assert "sources/retrieval-notes" in ids


def test_missing_required_field_is_an_error(populated):
    indexes.write_all(populated)
    # `description` is required for a concept by REQUIRED_FIELDS
    page(populated, "concepts/bare.md", {
        "type": "concept", "title": "Bare", "domain": "rag",
        "status": "seed", "created": TODAY, "updated": TODAY,
    })
    f, _pages = lint.lint(populated)
    assert "frontmatter" in checks(f.errors)
    assert "description" in messages(f.errors)


def test_missing_type_is_an_error(populated):
    page(populated, "concepts/untyped.md", {"title": "Untyped"})
    f, _pages = lint.lint(populated)
    assert any("`type`" in m["message"] for m in f.errors)


def test_domain_outside_the_taxonomy_is_an_error(populated):
    concept(populated, "off-taxonomy", domain="astrology")
    f, _pages = lint.lint(populated)
    assert "taxonomy" in checks(f.errors)
    assert "astrology" in messages(f.errors)


def test_invalid_status_is_an_error(populated):
    concept(populated, "bad-status", status="marinating")
    f, _pages = lint.lint(populated)
    assert "taxonomy" in checks(f.errors)
    assert "marinating" in messages(f.errors)


def test_broken_internal_link_is_an_error(populated):
    concept(populated, "dangling", body="See [Nowhere](does-not-exist.md).\n")
    f, _pages = lint.lint(populated)
    assert "links" in checks(f.errors)
    assert "does-not-exist.md" in messages(f.errors)


def test_source_pointing_at_a_missing_transcript_is_an_error(populated):
    source(populated, "ghost", body="No transcript.\n", raw="../raw/ghost.md")
    f, _pages = lint.lint(populated)
    assert "provenance" in checks(f.errors)


def test_transcript_with_no_source_page_is_a_warning_not_an_error(populated):
    indexes.write_all(populated)
    # A raw file nobody points at is recoverable — it must not block a CI gate.
    (populated.kb / "raw" / "orphan.md").write_text(
        "---\ntype: raw-transcript\nimmutable: true\nslug: orphan\n---\n\nText.\n",
        encoding="utf-8")
    f, _pages = lint.lint(populated)
    assert "provenance" in checks(f.warnings)
    assert "provenance" not in checks(f.errors)


def test_unindexed_page_is_reported(populated):
    indexes.write_all(populated)
    concept(populated, "not-in-any-index")
    f, _pages = lint.lint(populated)
    assert "index" in checks(f.errors) | checks(f.warnings)


def test_one_way_typed_link_is_a_graph_warning(populated):
    indexes.write_all(populated)
    # links *out* under a typed heading, with nothing linking back
    concept(populated, "one-way", body=(
        "## Builds on\n\n- [Chunking](chunking.md)\n"))
    f, _pages = lint.lint(populated)
    assert "graph" in checks(f.warnings)


def test_unparseable_frontmatter_is_an_error_not_a_crash(populated):
    (populated.kb / "concepts" / "broken.md").write_text(
        "---\ntype: concept\ntitle: [unclosed\n---\n\nbody\n", encoding="utf-8")
    f, _pages = lint.lint(populated)
    assert "parse" in checks(f.errors)


def test_render_report_mentions_the_failing_file(populated):
    concept(populated, "off-taxonomy", domain="astrology")
    f, pages = lint.lint(populated)
    report = lint.render_report(f, pages)
    assert "off-taxonomy" in report
    assert "astrology" in report


def test_valid_domains_comes_from_the_kb_taxonomy(populated):
    domains = lint.valid_domains(populated)
    assert "rag" in domains
    assert "astrology" not in domains
