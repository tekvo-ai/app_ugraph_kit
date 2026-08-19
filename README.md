# ugraph

[![ci](https://github.com/tekvo-ai/app_ugraph_kit/actions/workflows/ci.yml/badge.svg)](https://github.com/tekvo-ai/app_ugraph_kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ugraph-kit.svg)](https://pypi.org/project/ugraph-kit/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Turn any CLI input — clipboard, paste, pipe, file, or URL — into a
filesystem-native knowledge base that Obsidian and agents can read. Raw sources
remain inspectable, chunk IDs are content-addressed, and extracted quotes are
checked against source text before they become candidates.

> **Alpha:** the ingestion foundation is usable; retrieval and the evaluation
> harness are still under active development.

## Install

The distribution is named `ugraph-kit` because `ugraph` is already taken on
PyPI. The installed command is still the short form: `ugraph`.

```bash
# Recommended: isolated command-line install
uv tool install ugraph-kit

# Or with pipx
pipx install ugraph-kit
```

To use Anthropic or OpenAI synthesis:

```bash
uv tool install "ugraph-kit[api]"
# pipx install "ugraph-kit[api]" also works
```

Python 3.10+ is required.

## First run

Create a knowledge folder inside an Obsidian vault (or anywhere on disk):

```bash
ugraph init ~/Documents/MyVault/knowledge
```

That is the whole setup. `init` remembers the folder for this machine, so every
later session finds it from any directory — no `--kb`, no environment variable:

```bash
cd /anywhere
ugraph status        # works
```

To point at a different knowledge base later:

```bash
ugraph use ~/other/knowledge   # remembered from then on
ugraph use                     # print the current one
```

Anything that describes the current invocation still wins over the remembered
default, in this order: `--kb` → `UGRAPH_KB` → the nearest `ugraph.toml` → standing
inside a knowledge base → the remembered one.

Copy some text and run:

```bash
ugraph
```

On macOS and supported Linux desktops, ugraph reads the clipboard. Otherwise it
prompts for a paste terminated by Ctrl+D. Piped input is always supported:

```bash
printf 'Hybrid retrieval combines lexical and semantic search.' | ugraph
```

## Add a person

Copy a profile or talk URL (or paste a bio) and run `ugraph`. It previews the
detected identity and asks before writing.

The explicit, scriptable form is:

```bash
ugraph person "https://example.com/about"
ugraph person "https://example.com/about" --yes
```

This creates:

- `entities/people/<name>.md` — the canonical, minimally verified person page
- `resources/people/<name>.md` — a compatibility redirect for existing vaults

Repeating the command does not duplicate the person or overwrite
human-authored canonical content.

## Model setup

Capture and person resolution do not require an LLM. Synthesis is optional:

```bash
ugraph auth set anthropic
ugraph auth use anthropic

# or
ugraph auth set openai
ugraph auth use openai

# or a running local Ollama installation
ugraph auth use ollama
```

Check the active configuration with `ugraph auth status`.

### Tuning the model

Everything about the model is configuration, not code. In `ugraph.toml`:

```toml
[extract]
model = "claude-opus-5"  # any model, including ones released after this version
```

**A model ID selects its own backend.** `claude-*` goes to Anthropic, `gpt-*`/`o*` to
OpenAI, and anything else is treated as a local Ollama model — so a model released
tomorrow works without a code change or an entry in a list. Set `backend` explicitly
only to override that:

```toml
[extract]
backend = "api"   # api | ollama | claude-code
```

Naming a model whose provider you have no key for is refused by name rather than
silently sent to the other provider.

Token budgets are **discovered, not hardcoded**. ugraph asks your provider what the
model accepts and caches the answer for a day, so switching models needs no code
change and no setting. Override only if you want a tighter ceiling than the model's:

```toml
[extract]
max_tokens = 48000   # optional — omit to use the model's own maximum
thinking = "adaptive"  # optional — adaptive | disabled (Anthropic)
effort = "medium"      # optional — low | medium | high | xhigh | max (Anthropic)
temperature = 0.1      # optional — omitted by default
```

Every one of these is unset by default, which means "whatever the provider does". If
the provider cannot be reached to report its limits, the budget is derived from the
size of the prompt rather than guessed.

## Other commands

```bash
ugraph --kb ./knowledge ingest file ./note.md
printf 'a claim you care about' | ugraph --kb ./knowledge --yes
ugraph ps
ugraph logs
ugraph lint
ugraph verify
```

`--kb` is a global option and therefore comes before the subcommand.
Alternatively set `UGRAPH_KB` once or run inside a configured knowledge base.

## Reliability contract

The current test suite enforces:

1. Re-ingesting the same document creates no duplicates.
2. Editing a document updates only affected chunks.
3. Interrupting ingestion and rerunning completes cleanly.
4. Model quotes must occur verbatim in their source chunk.
5. Person capture is idempotent and preserves existing human content.

Operational events are appended to `runs.jsonl` and exposed through
`ugraph ps` and `ugraph logs`.

## Source

Canonical repo (Tekvo open source): https://github.com/tekvo-ai/app_ugraph_kit

This is the Tekvo AI open-source home for ugraph.  
Site: https://ugraph.build

## Development

```bash
git clone https://github.com/tekvo-ai/app_ugraph_kit.git
cd app_ugraph_kit
uv sync --extra dev
uv run pytest
uv build
```

Project artifacts:

- `docs/PRODUCT.md` — **product home**: goal, features, roadmap, public product log
- `CLAIMS.md` — claims backed by tests, ADRs, or measured runs
- `docs/adr/` — architecture decision records
- `docs/techniques/` — just-in-time technique scans
- `docs/releasing.md` — PyPI publish steps
- `CONTRIBUTING.md` — dev setup and the checks CI runs
- `CHANGELOG.md` — what changed, per release
- `eval/` — evaluation harness work
- `corpus/manifest.json` — loaded real-world data

Licensed under Apache-2.0.
