# Contributing to ugraph

Thanks for looking. ugraph is an open-source CLI that turns any input into a
filesystem-native, citation-verified knowledge base.

Read [`docs/PRODUCT.md`](docs/PRODUCT.md) first — it is the single source of truth for
the goal, the feature map, and what is deliberately out of scope.

## Setup

```bash
git clone https://github.com/tekvo-ai/app_ugraph_kit.git
cd app_ugraph_kit
uv sync --locked --extra dev
```

## The checks CI runs

All three must pass. They are the same commands the `ci` workflow runs, so there are
no surprises on a pull request:

```bash
uv run ruff check src tests   # lint (line length, imports, common bugs)
uv run mypy                   # type check (src/ugraph)
uv run pytest                 # tests + coverage floor
```

The coverage floor in `pyproject.toml` (`[tool.coverage.report] fail_under`) exists to
stop coverage sliding backwards. Raise it when you add tests; never lower it.

There is deliberately **no formatter**. `ruff check` enforces line length and import
order; the rest of the formatting is hand-tuned and stays that way.

## What a good change looks like

**Follow the deviation test** in `docs/PRODUCT.md` §3: if a change does not improve
*copy → `ugraph` → concepts/graph an agent can use* for someone who just installed the
CLI, it probably belongs in a later milestone.

**Keep the layering.** `cli.py` resolves a `Config`, calls one library function, and
formats the result. Library modules take a `Config`, return data, and never print.
Only `cli.py` and `wizard.py` call `print()`; only `cli.py` calls `sys.exit()`.
Library code raises typed errors (`ConfigError`, `IngestError`, `BackendError`, …).

**Keep the gates honest.** A quote that is not verbatim in its source chunk must not
become a candidate. `ugraph lint` and `ugraph verify` exit non-zero so they can be used
as CI gates — do not make them fail open.

**Write down decisions.** An architectural choice gets an ADR in `docs/adr/`, following
the existing ones: Decision, Why, Tradeoff, and an explicit **Kill criteria** section.

**Claims need evidence.** If you add a claim to `CLAIMS.md`, it must link to a real
test, ADR, or measured run. From that file: *if you cannot point to evidence, the claim
is not ready.*

## Releasing

Maintainers only — see [`docs/releasing.md`](docs/releasing.md). The version lives in
exactly one place, `src/ugraph/__init__.py`; `pyproject.toml` reads it from there.

## Reporting bugs

Open an issue with what you ran, what happened, and what you expected. `ugraph logs`
and `ugraph ps` output help. Never paste API keys — ugraph stores them in
`~/.config/ugraph/`, outside your knowledge base, precisely so they do not leak into
pasted output.
