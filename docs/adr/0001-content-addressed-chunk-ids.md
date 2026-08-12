# ADR-0001: Content-addressed chunk IDs for M0 ingest

- Status: Accepted
- Date: 2026-08-06

## Decision
Each chunk ID is `sha256(text + "|" + doc_slug)[:16]`. The document slug is included
so the same text pasted twice under different titles does not collide, while a true
re-ingest of the same document produces identical IDs and is skipped.

## Why
- Re-ingesting the same document must create zero duplicates.
- Editing one paragraph should update only affected chunk files.
- Content IDs make checkpoint resume safe: finished chunks are skipped on rerun.

## Tradeoff
Tiny risk of collision for adversarial edits is acceptable for a personal KB;
document slug namespace keeps accidental collisions low.

## Kill criteria
If semantic dedupe becomes a requirement (near-duplicates across documents), add a
separate similarity layer — do not break the deterministic ID contract.
