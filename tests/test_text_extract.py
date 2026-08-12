"""Text-mode Phase A: quotes are gated against content-addressed chunks."""

from __future__ import annotations

import json

from ugraph import ingest as ingest_mod
from ugraph.extract import Backend, extract_document, gate_text

DOC = """\
# Retrieval notes

Hybrid retrieval merges BM25 and dense rankings with RRF.

RRF is robust because it uses rank positions, not raw scores.

## Costs

Reranking adds latency but usually pays for itself on hard queries.
"""


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, payloads: list[str]):
        self.payloads = payloads
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return payload


GOOD = json.dumps({
    "yield": "medium",
    "concepts": [
        {"name": "rrf", "claim": "RRF merges rankings by position.",
         "verbatim_quote": "Hybrid retrieval merges BM25 and dense rankings with RRF."},
        {"name": "rerank-cost", "claim": "Reranking trades latency for quality.",
         "verbatim_quote": "Reranking adds latency but usually pays for itself on hard queries."},
    ],
})

PARAPHRASED = json.dumps({
    "yield": "medium",
    "concepts": [
        {"name": "rrf", "claim": "RRF merges rankings.",
         "verbatim_quote": "RRF combines lexical and semantic results using fusion."},
    ],
})


def _seed(cfg, slug="notes"):
    ingest_mod.ingest_document(cfg, DOC, slug=slug, title="Retrieval notes")
    return slug


def test_gate_text_anchors_and_rejects():
    chunks = [("aaa111", "alpha beta gamma"), ("bbb222", "delta epsilon zeta")]
    kept, rejected = gate_text(
        {"concepts": [
            {"name": "ok", "claim": "c", "verbatim_quote": "beta gamma"},
            {"name": "fabricated", "claim": "c", "verbatim_quote": "not here at all"},
            {"name": "empty", "claim": "c", "verbatim_quote": ""},
        ]},
        chunks,
    )
    assert [c["name"] for c in kept] == ["ok"]
    assert kept[0]["anchor"] == "aaa111"
    assert len(rejected) == 2


def test_extract_document_writes_anchored_candidates(cfg):
    slug = _seed(cfg)
    result = extract_document(cfg, slug, FakeBackend([GOOD]))

    assert result.written and result.concepts == 2
    data = json.loads((cfg.candidates / f"{slug}.json").read_text())
    real_ids = {ingest_mod.content_id(b, slug) for b in ingest_mod.chunk_text(DOC)}
    for concept in data["concepts"]:
        assert concept["anchor"] in real_ids


def test_extract_document_all_rejected_writes_no_yield(cfg):
    # Gate rejection is deterministic at temperature ~0 — retrying the same
    # prompt rarely fixes a paraphrasing model. The run writes a yield:none
    # candidate with the rejected claims visible instead of looping.
    slug = _seed(cfg)
    backend = FakeBackend([PARAPHRASED, GOOD])
    result = extract_document(cfg, slug, backend)

    assert result.written and result.concepts == 0
    assert result.attempts == 1 and backend.calls == 1
    assert len(result.rejected) == 1
    data = json.loads((cfg.candidates / f"{slug}.json").read_text())
    assert data["yield"] == "none"
    assert data["concepts"] == []


def test_extract_document_chunks_large_docs(cfg):
    filler = "\n\n".join(
        f"Paragraph {i} discusses indexing pipelines and retrieval tradeoffs "
        f"in enough detail to push the document past the chunked threshold."
        for i in range(60)
    )
    big = DOC + "\n\n" + filler
    assert sum(len(b) for b in ingest_mod.chunk_text(big)) > 5000

    slug = ingest_mod.ingest_document(cfg, big, slug="big", title="Big doc").slug
    backend = FakeBackend([GOOD])
    result = extract_document(cfg, slug, backend)

    assert backend.calls >= 2, "large doc should be extracted in chunk groups"
    assert result.written and result.concepts == 2  # duplicate groups merge


def test_extract_document_missing_slug(cfg):
    result = extract_document(cfg, "ghost", FakeBackend([GOOD]))
    assert not result.written
    assert "no raw document" in result.error
