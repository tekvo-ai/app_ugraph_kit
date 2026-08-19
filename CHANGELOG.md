# Changelog

All notable changes to `ugraph-kit`. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses
[semantic versioning](https://semver.org/).

Product context and roadmap live in [`docs/PRODUCT.md`](docs/PRODUCT.md).

## [0.1.0] - 2026-08-19

### Added
- Reports now say which knowledge base they describe. `ugraph status` prints the
  path and how it was resolved (`--kb flag`, `UGRAPH_KB`, a `ugraph.toml` path,
  `current directory`, `remembered default`), and both fields are in `--json`.
  `ugraph use` with no argument reports what is in effect *and* what is remembered,
  flagging when they differ — which is what happens whenever `UGRAPH_KB` or a nearby
  `ugraph.toml` overrides the machine default.
- `ugraph use PATH` points the machine at a knowledge base and remembers it. `ugraph
  init` does the same for the base it creates, so after first-run setup every session
  finds the KB from any directory with no flag and no environment variable. Local
  signals still win: `--kb` → `UGRAPH_KB` → nearest `ugraph.toml` → standing inside a
  KB → the remembered default.
- A model ID now selects its own backend and provider (`claude-*` → Anthropic,
  `gpt-*`/`o*` → OpenAI, anything else → local Ollama), so an unfamiliar or
  newly-released model routes correctly without a code change. A model whose provider
  has no key is refused by name instead of being sent to the other provider — which
  previously failed as a confusing auth error.
- `[project.urls]` metadata, so the PyPI page links to the repository and issues.
- `py.typed` marker — the documented library API now ships its type information.
- Lint (`ruff`), type checking (`mypy`), and a coverage floor, all enforced in CI.
- Tests for the eight previously untested modules — `verify`, `graph`, `lint`,
  `ledger`, `indexes`, `model`, `wizard`, `select`. Suite goes 58 → 228 tests and
  coverage 36% → 65%; `verify.py`, which backs the citation-hard claim, goes 0% → 87%.
- A shared `populated` KB fixture in `tests/conftest.py`, so the modules that read the
  graph test against pages that actually satisfy the SCHEMA.md contract.
- CI installs from the committed `uv.lock` (`uv sync --locked`) and runs a macOS job,
  so the clipboard path the daily loop depends on is actually exercised.
- Dependabot for `pip` and `github-actions`.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `.env.example`, and issue/PR
  templates.

### Changed
- Model token budgets are no longer hardcoded. `ugraph.limits` resolves the output
  ceiling per request — operator config, then the provider's own model metadata
  (cached for a day), then a budget derived from the prompt — so changing `model` is
  a config change rather than a code change. The Anthropic path previously sent a
  fixed `max_tokens=8000`, which truncated output on models with a larger ceiling and
  on models where thinking draws from the same budget.
- The Anthropic path now streams, which is what makes requesting a model's real
  ceiling safe (the SDK refuses large non-streaming requests to avoid HTTP timeouts).
- `[extract]` gained optional `max_tokens`, `thinking`, `effort`, and `temperature`.
  All are omitted from the request unless set, so an unset knob means "provider
  default" rather than a value ugraph chose.
- OpenAI requests omit the output ceiling entirely unless configured, letting the
  provider apply the model's own maximum; a configured ceiling is sent as
  `max_completion_tokens`, which is what current models expect.
- Default Anthropic model is `claude-opus-5` (was `claude-sonnet-4-5`, two
  generations stale).
- `ApiBackend.complete()` split into per-provider methods, replacing the
  if/else-on-provider body.
- `ugraph init` no longer assumes YouTube. It asks for "a file path or URL", only
  asks how many videos when the input is actually a feed, and leads its next-step
  hint with the bare `ugraph` capture loop.
- The version is single-sourced from `src/ugraph/__init__.py`; `pyproject.toml` reads
  it dynamically, so the two can no longer drift.

### Fixed
- `ugraph init` wrote a dead `github.com/saran-io/ugraph` URL into every generated
  `ugraph.toml`; it now points at the canonical repository.
- `ugraph init` given a person URL or a mistyped path surfaced a raw `OSError`. It now
  routes person URLs to person resolution and reports a missing file plainly.
- `runs.Run.__exit__` was annotated `-> bool`, which claims the context manager may
  swallow the exception it wraps. It always returned `False`; the annotation now says so.

First public release. The ingest spine — content-addressed chunks, idempotent and
resumable re-ingest, verbatim quote gates, `lint` / `verify` / `ledger` / `graph`,
optional local (Ollama) or API extraction, and person capture — plus everything
above.

[0.1.0]: https://github.com/tekvo-ai/app_ugraph_kit/releases/tag/v0.1.0
