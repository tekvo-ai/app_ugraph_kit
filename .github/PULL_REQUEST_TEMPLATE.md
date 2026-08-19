## What this changes

<!-- One or two sentences. Link the issue or the docs/PRODUCT.md feature ID. -->

## Why

<!-- The deviation test (docs/PRODUCT.md §3): does this improve
     copy → `ugraph` → concepts/graph an agent can use, for a fresh install? -->

## Checks

- [ ] `uv run ruff check src tests`
- [ ] `uv run mypy`
- [ ] `uv run pytest`
- [ ] Coverage floor not lowered
- [ ] Layering held: library code returns data, does not `print()` or `sys.exit()`
- [ ] ADR added under `docs/adr/` if this is an architectural decision
- [ ] `CLAIMS.md` row added if this makes a new claim, linked to real evidence
