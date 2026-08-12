# Technique scan — M0 chunking & doc IDs

Problem: split source text into chunks that (1) cite cleanly, (2) survive edits with
minimal churn, (3) can be content-addressed.

## Options
1. **Fixed window (tokens/words)** — simplest, but edits ripple across chunk IDs.
2. **Paragraph-ish** (chosen) — split on blank lines / headings; IDs track prose units.
3. **Semantic chunking (LLM/embedding boundaries)** — better cohesion, expensive and
   unstable for M0; revisit if M3 retrieval suffers on paragraph boundaries.

## Doc identity
- **Path-based** — breaks on rename.
- **Content hash only** — same text in two docs collides.
- **Slug + content hash** (chosen) — human-stable name + content-addressed chunks.

## Pick
Paragraph-ish chunks + `sha256(text|slug)` IDs.

## Switch criteria
Move to semantic chunking if hybrid retrieval shows consistent loss on long
multi-paragraph answers in the M3–M4 table.
