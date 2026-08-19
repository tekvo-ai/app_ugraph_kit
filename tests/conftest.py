from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ugraph import templates
from ugraph.config import CONTENT_DIRS, Config
from ugraph.store import write_md

TODAY = "2026-08-01"


@pytest.fixture()
def kb(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    (root / "raw").mkdir(parents=True)
    return root


@pytest.fixture()
def cfg(kb: Path) -> Config:
    return Config(kb=kb)


# ---------------------------------------------------------------------------
# A populated knowledge base
#
# The bare `kb` fixture above is enough for ingest, which only needs raw/. Every
# module that reads the *graph* — lint, verify, indexes, graph, ledger, model,
# select — needs pages that actually satisfy the OKF contract in SCHEMA.md, with
# real reciprocal links. Building that by hand in each test file is how the
# fixtures drift apart, so it lives here once.
# ---------------------------------------------------------------------------

def scaffold(root: Path) -> Config:
    """An empty but schema-valid knowledge base, the way `ugraph init` leaves one."""
    for rel in CONTENT_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    for name in ("SCHEMA.md", "taxonomy.json"):
        shutil.copy2(templates.path(name), root / name)
    return Config(kb=root)


def page(config: Config, rel: str, meta: dict, body: str = "") -> Path:
    """Write one page into the KB at a KB-relative path."""
    return write_md(config.kb / rel, body, meta)


def concept(config: Config, slug: str, *, title: str | None = None,
            domain: str = "rag", status: str = "seed", body: str = "",
            **extra) -> Path:
    meta = {
        "type": "concept",
        "title": title or slug.replace("-", " ").title(),
        "description": f"A concept about {slug}.",
        "domain": domain,
        "status": status,
        "created": TODAY,
        "updated": TODAY,
    }
    meta.update(extra)
    return page(config, f"concepts/{slug}.md", meta, body)


def entity(config: Config, slug: str, *, subtype: str = "tool",
           body: str = "", **extra) -> Path:
    dirs = {"tool": "tools", "person": "people", "organization": "organizations"}
    meta = {
        "type": "entity",
        "subtype": subtype,
        "title": slug.replace("-", " ").title(),
        "description": f"An entity: {slug}.",
        "created": TODAY,
        "updated": TODAY,
    }
    meta.update(extra)
    return page(config, f"entities/{dirs[subtype]}/{slug}.md", meta, body)


def source(config: Config, slug: str, *, source_type: str = "article",
           body: str = "", raw_text: str | None = None, **extra) -> Path:
    meta = {
        "type": "source",
        "source_type": source_type,
        "title": slug.replace("-", " ").title(),
        "description": f"A source: {slug}.",
        "slug": slug,
        "created": TODAY,
        "updated": TODAY,
    }
    meta.update(extra)
    if raw_text is not None:
        write_md(config.kb / "raw" / f"{slug}.md", raw_text,
                 {"type": "raw-transcript", "immutable": True, "slug": slug})
        meta.setdefault("raw", f"../raw/{slug}.md")
    return page(config, f"sources/{slug}.md", meta, body)


@pytest.fixture()
def populated(tmp_path: Path) -> Config:
    """Two linked concepts, an entity, and a source with its raw transcript.

    The concept pair links reciprocally under typed headings so that
    `lint.check_bidirectional` and `graph.build` both see real typed edges.
    """
    config = scaffold(tmp_path / "kb")

    concept(config, "hybrid-retrieval", domain="rag", body=(
        "Hybrid retrieval combines lexical and semantic search.\n\n"
        "## Builds on\n\n- [Chunking](chunking.md)\n\n"
        "## Tools\n\n- [Ugraph](../entities/tools/ugraph.md)\n\n"
        "## Sources\n\n- [Retrieval Notes](../sources/retrieval-notes.md)\n"
    ))
    concept(config, "chunking", domain="rag", body=(
        "Chunking splits a document into retrievable units.\n\n"
        "## Related\n\n- [Hybrid Retrieval](hybrid-retrieval.md)\n"
    ))
    entity(config, "ugraph", subtype="tool", body=(
        "A CLI that compiles a knowledge base.\n\n"
        "## Related\n\n- [Hybrid Retrieval](../../concepts/hybrid-retrieval.md)\n"
    ))
    source(config, "retrieval-notes", source_type="article",
           raw_text="Hybrid retrieval combines lexical and semantic search.",
           body="Notes on retrieval.\n")
    return config


@pytest.fixture()
def fresh(tmp_path: Path) -> Config:
    """A scaffolded but empty KB, for tests that need to control the whole corpus."""
    return scaffold(tmp_path / "kb")
