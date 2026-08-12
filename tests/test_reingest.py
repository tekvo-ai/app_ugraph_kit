"""
The M0 contract. These three tests are the product: everything in ingest.py exists
to make them pass, and they are the data-engineering fundamentals encoded as gates.
"""

from __future__ import annotations

import pytest

from ugraph.ingest import (
    IngestError,
    chunk_count,
    ingest_document,
)

DOC = """\
# Notes on eval

Eval is how you stop arguing from vibes.

Golden sets are small and biased; write the bias down.

## Why idempotency matters

Re-running a pipeline should be boring.
"""

EDITED = """\
# Notes on eval

Eval is how you stop arguing from vibes.

Golden sets are large and less biased if you hand-judge them.

## Why idempotency matters

Re-running a pipeline should be boring.
"""


def test_reingest_same_document_no_duplicates(cfg):
    first = ingest_document(cfg, DOC, slug="eval-notes", title="Eval notes")
    assert first.total_chunks == chunk_count(cfg, "eval-notes")
    assert first.written == first.total_chunks

    second = ingest_document(cfg, DOC, slug="eval-notes", title="Eval notes")
    assert second.written == 0
    assert second.skipped == second.total_chunks
    assert second.removed == 0
    assert chunk_count(cfg, "eval-notes") == first.total_chunks


def test_modified_document_updates_only_affected_chunks(cfg):
    first = ingest_document(cfg, DOC, slug="eval-notes", title="Eval notes")
    before = {p.read_text() for p in cfg.kb.glob(".ugraph/chunks/eval-notes/*.md")}

    second = ingest_document(cfg, EDITED, slug="eval-notes", title="Eval notes")
    after = {p.read_text() for p in cfg.kb.glob(".ugraph/chunks/eval-notes/*.md")}

    assert second.written == 1  # only the edited paragraph changed
    assert second.removed == 1
    assert len(after) == second.total_chunks
    assert before != after
    # unchanged chunks survived (intersection minus one)
    assert len(before & after) >= first.total_chunks - 1


def test_kill_resume_completes_cleanly(cfg):
    with pytest.raises(IngestError):
        ingest_document(
            cfg, DOC, slug="eval-notes", title="Eval notes",
            simulate_crash_after=1,
        )

    partial = chunk_count(cfg, "eval-notes")
    assert 0 < partial < 3

    final = ingest_document(cfg, DOC, slug="eval-notes", title="Eval notes")
    assert final.resumed is True
    assert final.skipped == partial
    assert chunk_count(cfg, "eval-notes") == final.total_chunks
    assert final.total_chunks == 3
