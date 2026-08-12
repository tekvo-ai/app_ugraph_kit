# ADR-0000: M0 restart — learn-by-building with provenance-first retrieval

- Status: Accepted
- Date: 2026-08-06

## Context
ugraph started as “markdown only, no embeddings.” To become a production-grade AI
system with defendable fundamentals, we pivoted: provenance remains the moat, but
retrieval quality must be measured. Six-month scope is explicit.

## Decision
- Keep `raw/` + `sources/` + verify gates as source of truth for citations.
- Add `ingest` spine now (M0): content-addressed IDs, checkpoints, copy-paste capture.
- Defer: memory frameworks, OCR/vision, speculative performance study.
- Staged sources: text/copy-paste (M0) → podcast/YouTube transcript (M5) → MCP (M7).

## Consequences
- First technique scan happens at M0 for chunking/IDs (not before).
- CI + packaging landed before retrieval work so claims are public and reproducible.

## Kill criteria
If eval never shows a delta between retrieval strategies by M4, revisit whether the
retrieval layer earns its complexity.
