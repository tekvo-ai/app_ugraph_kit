# Technique — chunk-hash reuse (omni-macos §3.2)

Problem: after the first embed pass, the cost that matters is re-encoding a file
the user just edited. Most chunks did not change.

## Options
1. **Re-embed whole file** — simple, wastes accelerator time on every save.
2. **Whole-file content cache** — misses partial edits.
3. **Per-chunk hash reuse** (chosen) — skip the forward pass when
   `hash(text, len, dim, chunking)` matches the stored row for that chunk id.

## Pick
Paper mechanism from Xiao, *omni-macos* (2026) §3.2, adapted to ugraph's
paragraph chunks and Mac-local Ollama (`nomic-embed-text` by default).

- Store: `<kb>/.ugraph/vectors/<slug>.json` (derived; regenerable)
- Model change → forced full re-index (encoder id not in the hash key)
- Modalities: `modality` field on each row; text first, image/audio/video later

## Measure
```bash
ugraph embed --bench                  # real Ollama on Mac
ugraph embed --bench --fake           # offline / CI
```

## Switch criteria
Keep this as the default index path. Add the paper's 4-bit scan funnel only when
corpus scan time or memory shows up in M1 retrieval eval.
