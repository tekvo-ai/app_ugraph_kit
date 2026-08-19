"""The graph is a *derived view* — it never writes to the KB.

Provenance edges dominate a healthy KB, so `include_provenance` and `types` are the
two knobs that decide whether a picture shows idea structure or a wall of sources.
Every exporter must produce parseable output for an empty graph as well as a full one.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest
from conftest import concept, scaffold

from ugraph import graph as graph_mod


def relations(g) -> set[str]:
    return {e["relation"] for e in g["edges"]}


def node_ids(g) -> set[str]:
    return {n["id"] for n in g["nodes"]}


# --- build ------------------------------------------------------------------

def test_build_writes_nothing_to_the_kb(populated):
    before = {p: p.read_bytes() for p in populated.kb.rglob("*.md")}
    graph_mod.build(populated)
    assert {p: p.read_bytes() for p in populated.kb.rglob("*.md")} == before


def test_build_makes_a_node_per_page(populated):
    g = graph_mod.build(populated)
    assert "concepts/hybrid-retrieval" in node_ids(g)
    assert "entities/tools/ugraph" in node_ids(g)
    assert "sources/retrieval-notes" in node_ids(g)


def test_typed_headings_become_named_relations(populated):
    g = graph_mod.build(populated)
    assert "builds on" in relations(g)
    assert "tools" in relations(g)


def test_links_to_a_source_are_provenance_edges(populated):
    g = graph_mod.build(populated)
    assert graph_mod.RELATION_PROVENANCE in relations(g)


def test_include_provenance_false_drops_exactly_those_edges(populated):
    with_prov = graph_mod.build(populated, include_provenance=True)
    without = graph_mod.build(populated, include_provenance=False)
    assert graph_mod.RELATION_PROVENANCE in relations(with_prov)
    assert graph_mod.RELATION_PROVENANCE not in relations(without)
    assert len(without["edges"]) < len(with_prov["edges"])


def test_types_filter_restricts_the_nodes(populated):
    g = graph_mod.build(populated, types={"concept"})
    assert all(n["id"].startswith("concepts/") for n in g["nodes"])


def test_a_repeated_link_produces_one_edge(populated):
    concept(populated, "repeater", body=(
        "## Related\n\n- [Chunking](chunking.md)\n- [Chunking again](chunking.md)\n"))
    g = graph_mod.build(populated)
    edges = [e for e in g["edges"]
             if e["source"] == "concepts/repeater" and e["target"] == "concepts/chunking"]
    assert len(edges) == 1


def test_links_leaving_the_kb_are_not_edges(populated):
    concept(populated, "outbound", body="See [the web](https://example.com).\n")
    g = graph_mod.build(populated)
    assert not [e for e in g["edges"] if e["source"] == "concepts/outbound"]


def test_build_is_deterministic(populated):
    assert graph_mod.build(populated) == graph_mod.build(populated)


# --- exporters --------------------------------------------------------------

def test_to_json_is_valid_json(populated):
    decoded = json.loads(graph_mod.to_json(graph_mod.build(populated)))
    assert decoded["nodes"] and decoded["edges"]


def test_to_graphml_is_valid_xml(populated):
    root = ET.fromstring(graph_mod.to_graphml(graph_mod.build(populated)))
    assert root.tag.endswith("graphml")


def test_to_dot_declares_a_digraph(populated):
    dot = graph_mod.to_dot(graph_mod.build(populated))
    assert dot.strip().startswith("digraph")
    assert dot.strip().endswith("}")


def test_to_d3_is_an_html_document_carrying_the_graph(populated):
    html = graph_mod.to_d3(graph_mod.build(populated), title="My graph")
    assert html.lower().startswith("<!doctype html>")
    assert "My graph" in html
    # the graph data is inlined, so the file needs the network only for d3 itself
    assert "concepts/hybrid-retrieval" in html


def test_to_canvas_is_valid_json_with_file_nodes(populated):
    canvas = json.loads(graph_mod.to_canvas(graph_mod.build(populated), populated))
    assert canvas["nodes"]
    # file nodes point at the real pages, so clicking opens the note itself
    assert any(n.get("type") == "file" for n in canvas["nodes"])


@pytest.mark.parametrize("fmt", ["json", "graphml", "dot"])
def test_every_exporter_survives_an_empty_graph(tmp_path, fmt):
    empty = graph_mod.build(scaffold(tmp_path / "empty"))
    assert empty["nodes"] == []
    assert graph_mod.render(empty, fmt)


# --- render dispatch --------------------------------------------------------

def test_render_dispatches_by_name(populated):
    g = graph_mod.build(populated)
    assert graph_mod.render(g, "json") == graph_mod.to_json(g)
    assert graph_mod.render(g, "dot") == graph_mod.to_dot(g)


def test_render_canvas_requires_a_config(populated):
    g = graph_mod.build(populated)
    with pytest.raises(ValueError) as exc:
        graph_mod.render(g, "canvas")
    assert "Config" in str(exc.value)
    assert graph_mod.render(g, "canvas", config=populated)


def test_render_names_the_known_formats_when_asked_for_a_bad_one(populated):
    with pytest.raises(ValueError) as exc:
        graph_mod.render(graph_mod.build(populated), "yaml")
    message = str(exc.value)
    assert "yaml" in message
    for known in ("json", "graphml", "dot", "canvas"):
        assert known in message


# --- layout -----------------------------------------------------------------

def test_layout_places_every_node(populated):
    g = graph_mod.build(populated)
    positions = graph_mod.layout(g, iterations=5)
    assert set(positions) == node_ids(g)
    assert all(isinstance(x, int) and isinstance(y, int)
               for x, y in positions.values())


def test_layout_is_deterministic(populated):
    g = graph_mod.build(populated)
    assert graph_mod.layout(g, iterations=5) == graph_mod.layout(g, iterations=5)
