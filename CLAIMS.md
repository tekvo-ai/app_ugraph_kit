# Claims ledger

One row per claim you can defend in an interview. Evidence must link to a real run, test, or ADR.

| Claim | Evidence | Job note |
|-------|----------|----------|
| M0 ingest is idempotent under interruption | tests/test_reingest.py (3 tests) | Pipelines that resume without corrupting data |
| Chunk IDs are content-addressed | ugraph/ingest.py::content_id + ADR-0001 | Stable IDs let you diff, dedupe, and migrate |
| Technique choice: paragraph-ish chunks before semantic chunking | docs/techniques/m0-chunking.md | Simple before fancy until eval says otherwise |
| A 7B local model is safe for extraction because paraphrase fails a substring gate, not a trust check | first real run: 4 kept / 1 rejected (qwen2.5-coder:7b); tests/test_text_extract.py | Generation–verification loop turns weak models into reliable pipelines at the cost of retries |
| UGRAPH_KB resolves vault config identically to --kb | tests/test_config_env.py (found in the wild, first demo) | Env-based config is where silent setting loss lives |
| YouTube `--repair-state` drops polluted/missing IDs scoped to the feed slug | tests/test_resume_checkpoints.py; founder_os playlist 167→15 then 44 after re-ingest | Multi-channel KBs must not let one feed absorb another's youtube_ids |
| Extract aborts the batch on billing/auth hard failures | tests/test_resume_checkpoints.py; live Anthropic credit-fail stopped at 1/15 | Resume command printed; no credit burn on the rest of `--limit` |

_Add a row every milestone. If you cannot point to evidence, the claim is not ready._
