"""model.py is the OKF layer every other module builds on.

Link parsing in particular carries a real hazard: a code block that *documents*
a link must not become a graph edge, and a broken one must not become a lint error.
"""

from __future__ import annotations

from pathlib import Path

from conftest import concept, entity

from ugraph import model

# --- link parsing -----------------------------------------------------------

def test_get_md_links_returns_text_and_target():
    assert model.get_md_links("see [Chunking](chunking.md) now") == [
        ("Chunking", "chunking.md")]


def test_images_are_not_links():
    assert model.get_md_links("![diagram](diagram.png)") == []


def test_fenced_code_is_not_scanned_for_links():
    body = "real [A](a.md)\n\n```\nexample [B](b.md)\n```\n"
    assert model.get_md_links(body) == [("A", "a.md")]


def test_inline_code_is_not_scanned_for_links():
    assert model.get_md_links("use `[B](b.md)` in a page") == []


def test_strip_code_false_sees_links_inside_code():
    body = "```\n[B](b.md)\n```"
    assert model.get_md_links(body, strip_code=False) == [("B", "b.md")]


def test_link_titles_are_stripped_from_the_target():
    assert model.get_md_links('[A](a.md "the title")') == [("A", "a.md")]


def test_get_wikilinks():
    assert model.get_wikilinks("see [[Hybrid Retrieval]] and [[Chunking]]") == [
        "Hybrid Retrieval", "Chunking"]


# --- path resolution --------------------------------------------------------

def test_resolve_md_link_walks_relative_paths(populated):
    src = populated.kb / "concepts" / "hybrid-retrieval.md"
    resolved = model.resolve_md_link(src, "../entities/tools/ugraph.md")
    assert resolved == (populated.kb / "entities" / "tools" / "ugraph.md")


def test_resolve_md_link_ignores_external_targets(populated):
    src = populated.kb / "concepts" / "hybrid-retrieval.md"
    for target in ("https://example.com", "mailto:a@b.c", "#anchor"):
        assert model.resolve_md_link(src, target) is None


def test_relpath_between_round_trips(populated):
    a = populated.kb / "concepts" / "hybrid-retrieval.md"
    b = populated.kb / "entities" / "tools" / "ugraph.md"
    rel = model.relpath_between(a, b)
    assert model.resolve_md_link(a, rel) == b


# --- pages ------------------------------------------------------------------

def test_page_id_is_the_kb_relative_path_without_suffix(populated):
    page = model.load_page(populated.kb / "concepts" / "chunking.md", populated)
    assert page.id == "concepts/chunking"
    assert page.rel == "concepts/chunking.md"


def test_page_id_uses_posix_separators_everywhere(populated):
    page = model.load_page(populated.kb / "entities" / "tools" / "ugraph.md", populated)
    assert "\\" not in page.id
    assert page.id == "entities/tools/ugraph"


def test_is_content_covers_exactly_concept_entity_source(populated):
    kinds = {p.type: p.is_content for p in model.iter_pages(populated)}
    assert kinds["concept"] is True
    assert kinds["entity"] is True
    assert kinds["source"] is True


def test_iter_pages_finds_every_written_page(populated):
    ids = {p.id for p in model.iter_pages(populated)}
    assert {"concepts/chunking", "concepts/hybrid-retrieval",
            "entities/tools/ugraph", "sources/retrieval-notes"} <= ids


def test_page_paths_are_sorted_and_stable(populated):
    twice = [list(model.page_paths(populated)) for _ in range(2)]
    assert twice[0] == twice[1]
    assert twice[0] == sorted(twice[0])


def test_page_paths_excludes_raw_transcripts_by_default(populated):
    names = {p.name for p in model.page_paths(populated)}
    assert "retrieval-notes.md" in names          # the source page
    with_raw = list(model.page_paths(populated, include_raw=True))
    assert len(with_raw) > len(list(model.page_paths(populated)))


def test_page_paths_skips_reserved_names(populated):
    from ugraph import indexes
    indexes.write_all(populated)
    names = {p.name for p in model.page_paths(populated)}
    assert "index.md" not in names
    assert "SCHEMA.md" not in names


# --- typed edges ------------------------------------------------------------

def test_get_typed_edges_groups_targets_by_heading(populated):
    page = model.load_page(populated.kb / "concepts" / "hybrid-retrieval.md", populated)
    edges = model.get_typed_edges(page)
    assert edges["builds on"] == ["chunking.md"]
    assert edges["tools"] == ["../entities/tools/ugraph.md"]
    assert edges["sources"] == ["../sources/retrieval-notes.md"]


def test_untyped_headings_are_not_edges(populated):
    concept(populated, "prose", body="## Notes\n\n- [Chunking](chunking.md)\n")
    page = model.load_page(populated.kb / "concepts" / "prose.md", populated)
    assert model.get_typed_edges(page) == {}


def test_typed_heading_with_no_links_is_omitted(populated):
    concept(populated, "empty-section", body="## Builds on\n\nnothing yet.\n")
    page = model.load_page(populated.kb / "concepts" / "empty-section.md", populated)
    assert "builds on" not in model.get_typed_edges(page)


# --- backlinks and registry -------------------------------------------------

def test_build_backlink_map_points_target_back_at_its_referrers(populated):
    pages = list(model.iter_pages(populated))
    backlinks = model.build_backlink_map(pages)
    chunking = (populated.kb / "concepts" / "chunking.md").resolve()
    referrers = {Path(p).name for p in backlinks.get(chunking, set())}
    assert "hybrid-retrieval.md" in referrers


def test_concept_registry_includes_entities_by_default(populated):
    registry = model.concept_registry(populated)
    assert "concepts/chunking" in registry
    assert "entities/tools/ugraph" in registry
    assert "sources/retrieval-notes" not in registry


def test_concept_registry_can_exclude_entities(populated):
    registry = model.concept_registry(populated, include_entities=False)
    assert "entities/tools/ugraph" not in registry


def test_registry_digest_is_one_line_per_page_and_sorted(populated):
    entity(populated, "aardvark", subtype="tool")
    digest = model.registry_digest(populated).splitlines()
    assert all(line.startswith("- ") for line in digest)
    assert digest == sorted(digest)


def test_valid_domains_reads_the_kb_taxonomy(populated):
    assert "rag" in model.valid_domains(populated)
