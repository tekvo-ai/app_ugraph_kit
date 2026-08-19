"""
wizard.py — the interactive `ugraph init`.

Running `ugraph init` with no arguments should get a stranger from nothing to a working
knowledge base without reading anything. Everything it asks has a sensible default, and
every answer is also expressible as a flag so scripts and CI never see a prompt.

The wizard's real job is preventing the two mistakes that a first-time user makes and
cannot easily undo: scaffolding over their existing notes, and not knowing that the
extraction step needs something ugraph deliberately does not include.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKENDS = [
    ("claude-code", "Claude Code",
     "you already have it; best quality, does every phase"),
    ("api", "An API key",
     "Anthropic or OpenAI. Needs: pip install 'ugraph-kit[api]'"),
    ("ollama", "Local model via Ollama",
     "free and private; good for extraction, not for merging"),
    ("later", "Decide later",
     "ingest now, choose when you get there"),
]


def interactive() -> bool:
    """Only prompt a human at a terminal. A pipe or CI must never block."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(130) from None
    return answer or default


def ask_choice(prompt: str, options: list[tuple[str, str, str]], default: int = 1) -> str:
    print(f"  {prompt}")
    for i, (_, label, note) in enumerate(options, 1):
        print(f"    {i}) {label:<24} {note}")
    while True:
        raw = ask("choose", str(default))
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(f"    enter a number between 1 and {len(options)}")


def find_vault(start: Path) -> Path | None:
    """Nearest enclosing note-taking vault, if any.

    `.obsidian` is the common case. Logseq and Foam are also plain markdown, so they
    work identically — the marker directory is just how we recognise one to give a
    better default.
    """
    current = start.resolve()
    for directory in (current, *current.parents):
        for marker in (".obsidian", ".logseq", ".foam"):
            if (directory / marker).is_dir():
                return directory
    return None


def is_feed_url(value: str) -> bool:
    """Whether this input is a YouTube feed, and so has a video count to cap.

    Imported lazily: `ugraph init` should not pay for the source adapter just to
    classify one answer, and wizard.py is otherwise free of ugraph imports.
    """
    from ugraph.sources.youtube import is_feed_url as _is_feed_url

    return _is_feed_url(value.strip())


def run(cwd: Path | None = None) -> dict:
    """Ask the questions and return the answers. Writes nothing itself."""
    cwd = (cwd or Path.cwd()).resolve()
    answers: dict = {}

    print()
    vault = find_vault(cwd)
    if vault:
        print(f"  Found a vault at {vault}")
        base = vault
    else:
        print("  No Obsidian/Logseq vault detected here.")
        print("  That is fine — a knowledge base is just a folder of markdown.")
        base = cwd
    print()

    # 1. Where the KB goes. Never the vault root: its schema is strict, and linting a
    #    vault full of ordinary notes reports every one of them as malformed.
    name = ask("Knowledge base folder", "knowledge")
    answers["kb"] = (base / name).resolve()
    if answers["kb"] == base:
        print("    (a knowledge base needs its own folder — using ./knowledge)")
        answers["kb"] = base / "knowledge"

    # 2. Something to ingest. Optional; an empty KB is a valid starting point.
    #    The daily loop is "copy anything, type ugraph", so this must not privilege
    #    one source type — a file on disk is at least as likely as a channel URL.
    print()
    source = ask("Something to ingest now? (file path or URL — blank to skip)", "")
    answers["source"] = source or None
    if source and is_feed_url(source):
        # Only a feed has a countable backlog worth capping. Asking "how many" about
        # a single file would be a question with no meaningful answer.
        raw = ask("How many videos to start with", "25")
        answers["limit"] = int(raw) if raw.isdigit() else 25

    # 3. The part people do not expect: ugraph runs no model. Say so here rather than
    #    letting them discover it at step four.
    print()
    print("  Turning what you capture into linked concepts needs a model.")
    print("  ugraph itself never calls one — you choose what does.")
    answers["backend"] = ask_choice("Which?", BACKENDS, default=1)

    return answers


def summary(answers: dict, config_path: Path) -> str:
    kb = answers["kb"]
    lines = ["", f"  Knowledge base   {kb}", f"  Config           {config_path}"]
    if answers.get("source"):
        lines.append(f"  Ingested from    {answers['source']}")
    lines += ["", "  Next:"]

    backend = answers.get("backend")
    # The daily loop is the product: copy anything, type `ugraph`, confirm. Lead with
    # it. A source-specific command is an option below it, never the headline.
    lines.append("    ugraph                    # capture clipboard / paste / pipe")
    if not answers.get("source"):
        retry = answers.get("retry_command")
        if retry:
            # Repeat the command for the input they already named rather than a
            # placeholder — this branch is where a failed ingest lands, and retyping
            # it is friction at exactly the moment something already went wrong.
            lines.append(f"    {retry}")
        else:
            lines += ["    ugraph ingest file ./notes.md",
                      "    ugraph ingest youtube <channel-or-playlist-url> --limit 10"]
    if backend == "claude-code":
        lines += ["    ugraph skills install",
                  "    then in Claude Code:  /channel-to-kb"]
    elif backend == "api":
        lines += ["    pip install 'ugraph-kit[api]'",
                  "    export ANTHROPIC_API_KEY=...    # or OPENAI_API_KEY",
                  "    ugraph extract --backend api"]
    elif backend == "ollama":
        lines += ["    ollama pull qwen2.5-coder:7b",
                  "    ugraph extract --backend ollama",
                  "",
                  "    Local models handle extraction well but not the merging step —",
                  "    `ugraph verify` catches a bad quote; nothing catches bad judgement."]
    else:
        lines.append("    ugraph extract --help     # when you are ready")

    lines += ["", "  Then:  ugraph index && ugraph lint && ugraph ledger"]
    return "\n".join(lines)


def toml_for(answers: dict, config_path: Path) -> str:
    kb: Path = answers["kb"]
    try:
        rel = kb.relative_to(config_path.parent)
        kb_value = str(rel)
    except ValueError:
        kb_value = str(kb)

    lines = [
        "# ugraph configuration — https://github.com/tekvo-ai/app_ugraph_kit",
        "",
        f'kb = "{kb_value}"',
    ]
    backend = answers.get("backend")
    if backend and backend != "later":
        lines += ["", "[extract]", f'backend = "{backend}"']
        if backend == "ollama":
            lines.append('model = "qwen2.5-coder:7b"')
    return "\n".join(lines) + "\n"
