"""
cli.py — the `ugraph` command.

Deliberately thin. Every subcommand resolves a Config, calls one library function, and
formats the result. Logic that lives here cannot be tested or reused, so it does not live
here.

Exit codes matter: `lint`, `verify`, and `index --check` are meant to be usable as CI
gates, so they exit non-zero on failure and stay quiet on success.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from ugraph import __version__
from ugraph import config as config_mod

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _config(args) -> config_mod.Config:
    try:
        return config_mod.load(kb=getattr(args, "kb", None))
    except config_mod.ConfigError as exc:
        sys.exit(f"ugraph: {exc}")


def _bundled(name: str) -> Path:
    """Locate a directory shipped inside the wheel (skills/, templates/)."""
    packaged = Path(__file__).parent / "_bundled" / name
    if packaged.is_dir():
        return packaged
    # Running from a source checkout rather than an installed wheel.
    repo = Path(__file__).resolve().parents[2] / name
    if repo.is_dir():
        return repo
    sys.exit(f"ugraph: cannot locate bundled {name}/ — is the install complete?")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    answers = None
    if not args.path:
        from ugraph import wizard
        if not wizard.interactive():
            sys.exit("ugraph: init needs a path when not run interactively\n"
                     "  e.g.  ugraph init ./knowledge")
        answers = wizard.run()
        args.path = str(answers["kb"])

    root = Path(args.path).expanduser().resolve()
    templates = _bundled("templates")

    existing = [p for p in (root / "SCHEMA.md", root / "taxonomy.json") if p.exists()]
    if existing and not args.force:
        print(f"ugraph: {root} already looks like a knowledge base.")
        for p in existing:
            print(f"  exists: {p.name}")
        print("  use --force to overwrite the scaffold (content is never touched)")
        return 1

    # A knowledge base needs its own directory. Pointing `init` at an Obsidian vault
    # root — the obvious thing to try — used to scatter concepts/, entities/, raw/ and
    # sources/ in among the user's real folders, write an index.md that could clobber
    # an existing note, drop the config file OUTSIDE the vault, and then report every
    # personal note as a malformed page. Refuse, and say where to put it instead.
    if not args.force:
        suggestion = (root / "knowledge") if root.name != "knowledge" else (root / "kb")
        try:
            shown = suggestion.relative_to(Path.cwd())
        except ValueError:
            shown = suggestion

        # Any of the markdown note apps, not just Obsidian — a Logseq user pointing
        # init at their graph root hits exactly the same mess.
        marker = next((m for m in (".obsidian", ".logseq", ".foam")
                       if (root / m).is_dir()), None)
        if marker:
            app = {".obsidian": "an Obsidian vault", ".logseq": "a Logseq graph",
                   ".foam": "a Foam workspace"}[marker]
            print(f"ugraph: {root} is {app} root.")
            print()
            print("  A knowledge base needs its own folder inside the vault, otherwise")
            print("  its directories land beside your real notes and `ugraph lint` treats")
            print("  every note you already have as a malformed page.")
            print()
            print(f"  Try:  ugraph init {shown}")
            return 1

        strays = [p for p in root.glob("*.md")
                  if p.name not in {"SCHEMA.md", "README.md", "index.md"}]
        strays += [p for p in root.glob("*/*.md")][:1]
        if strays:
            print(f"ugraph: {root} already contains markdown files.")
            for p in strays[:4]:
                print(f"    {p.relative_to(root)}")
            if len(strays) > 4:
                print(f"    … and {len(strays) - 4} more")
            print()
            print("  A knowledge base needs an empty directory of its own — `ugraph lint`")
            print("  would report every one of these as a malformed page.")
            print()
            print(f"  Try:  ugraph init {shown}")
            print("  Or pass --force if this really is meant to be the knowledge base.")
            return 1

    for rel in config_mod.CONTENT_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    for name in ("SCHEMA.md", "taxonomy.json"):
        shutil.copy2(templates / name, root / name)

    cfg_path = root.parent / config_mod.CONFIG_FILENAME
    if not cfg_path.exists():
        from ugraph import wizard
        cfg_path.write_text(
            wizard.toml_for(answers, cfg_path) if answers
            else f'kb = "{root.name}"\n',
            encoding="utf-8")

    from ugraph import indexes
    cfg = config_mod.load(kb=root)
    indexes.write_all(cfg)

    print(f"Initialized knowledge base at {root}")
    print(f"  wrote SCHEMA.md, taxonomy.json, {len(config_mod.CONTENT_DIRS)} directories")
    print(f"  wrote {cfg_path}")

    # The wizard asked which model backend and whether to ingest a channel. Answering
    # those and then printing the same generic block as a bare `init` wastes the only
    # thing the questions were for — somebody who picked Ollama needs to hear about
    # `ollama pull`, not about skills install.
    if answers:
        if answers.get("channel"):
            _ingest_from_init(cfg, answers)
        from ugraph import wizard
        print(wizard.summary(answers, cfg_path))
        return 0

    # Config resolution walks UP from the working directory, so a bare `ugraph ingest`
    # only finds ugraph.toml when you are at or below its directory. Printing the bare
    # command here sent people straight into "cannot find a knowledge base" — the very
    # next thing they ran after a successful init. Emit commands that work from where
    # the user is actually standing.
    try:
        shown = root.relative_to(Path.cwd())
    except ValueError:
        shown = root
    reachable = config_mod.find_config(Path.cwd()) is not None
    prefix = "" if reachable else f"--kb {shown} "

    print()
    print("Next:")
    print(f"  ugraph {prefix}            # capture clipboard / paste (no model required)")
    print(f"  ugraph {prefix}ingest youtube <channel-or-playlist-url> --limit 10")
    print(f"  ugraph {prefix}auth status # optional: API / Ollama for synthesize")
    print(f"  ugraph {prefix}skills install")
    if not reachable:
        print()
        print(f"  (or `cd {cfg_path.parent.name}` and drop the --kb flag)")
    return 0


def _ingest_from_init(cfg, answers: dict) -> None:
    """Fetch the channel the wizard asked about, if the user named one.

    Asking "which channel to ingest" and then only printing a command to type is a
    question that did nothing. But this must never abort a successful scaffold: a
    missing yt-dlp or a dead network leaves a perfectly good empty KB, so failures
    here degrade to the command the user can run later.
    """
    from ugraph.sources import youtube

    url, limit = answers["channel"], answers.get("limit", 25)
    print(f"\nFetching up to {limit} transcripts from {url} …")

    def progress(i, total, vid, title):
        print(f"  [{i}/{total}] {title[:58]}")

    try:
        result = youtube.ingest(cfg, url, limit=limit, progress=progress)
    except FileNotFoundError:
        answers["retry_channel"] = answers["channel"]
        answers["channel"] = None  # so the summary prints the ingest command again
        print("  yt-dlp is not installed — skipping for now.")
        print("  Install it (brew install yt-dlp) and run the ingest command below.")
        return
    except Exception as exc:
        answers["channel"] = None
        print(f"  ingest failed: {exc}")
        print("  The knowledge base is fine — run the ingest command below when ready.")
        return

    print(f"  ingested {result['written']}, skipped {result['skipped']}")


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def cmd_ingest(args) -> int:
    cfg = _config(args)
    if args.source == "file":
        from ugraph import ingest as ingest_mod

        result = ingest_mod.ingest_path(cfg, args.url)
        print(f"Ingested {result.slug}: {result.written} new, "
              f"{result.skipped} skipped, {result.removed} removed "
              f"({result.total_chunks} chunk(s) total)")
        return 0

    if args.source != "youtube":
        sys.exit(f"ugraph: unknown source '{args.source}' (only 'youtube' so far)")

    from ugraph.sources import youtube

    if getattr(args, "repair_state", False):
        repaired = youtube.repair_state(cfg, args.url, slug=args.slug)
        print(f"Repaired state for {repaired['channel']}")
        if repaired.get("slug"):
            print(f"  slug: {repaired['slug']}")
        print(f"  ingested before: {repaired['before']}")
        print(f"  kept (on disk):  {repaired['kept']}")
        print(f"  dropped:         {repaired['removed']}")
        if repaired.get("merged_aliases"):
            print(f"  merged alias keys: {len(repaired['merged_aliases'])}")
        print("  Re-run ingest (without --repair-state) to fetch missing videos.")
        return 0

    def progress(i, total, vid, title):
        print(f"[{i}/{total}] {vid}  {title[:58]}")

    try:
        result = youtube.ingest(
            cfg, args.url,
            limit=args.limit, slug=args.slug, dry_run=args.dry_run,
            sleep=args.sleep, force=args.force, newest=args.newest,
            retry_failed=args.retry_failed, progress=progress,
        )
    except FileNotFoundError as exc:
        sys.exit(f"ugraph: {exc}")
    except RuntimeError as exc:
        sys.exit(f"ugraph: {exc}")

    # Recovering IDs from disk means the state file was missing or incomplete. Silent
    # self-healing is the wrong kind of quiet: the user should know their state was
    # rebuilt, because it is also the signal that something deleted or moved it.
    recovered = result.get("recovered_from_disk", 0)
    if recovered:
        print(f"  [state] recovered {recovered} previously-ingested video(s) "
              "from transcripts on disk")

    if args.dry_run:
        for v in result.get("videos", []):
            print(f"  {v['id']}  {v.get('title', '')[:70]}")
        print(f"\n{len(result.get('videos', []))} video(s) would be ingested.")
        if result.get("known_failed"):
            print(f"  ({result['known_failed']} previously failed, excluded — "
                  "use --retry-failed to reconsider)")
        return 0

    for warning in result.get("warnings", []):
        print(f"  [warn] {warning}")
    print(f"\nIngested {result['written']}, skipped {result['skipped']}.")
    # With --newest the listing is a window over the channel, not the channel, so
    # "151/10 of the listing" is not a ratio — it is two unrelated numbers.
    if args.newest:
        print(f"  {result['total_ingested']} video(s) held from this channel; "
              f"looked at the {result['listed']} most recent.")
    else:
        print(f"  {result['total_ingested']}/{result['listed']} "
              "of the listing now in the KB.")
    if result.get("failed"):
        print(f"  {result['failed']} video(s) recorded as unfetchable (no captions); "
              "they will not be retried. --retry-failed reconsiders them.")

    # The product promise for a feed URL is end-to-end: raw → candidates → draft
    # concepts → indexes. Capture already auto-synthesizes; YouTube must too, or
    # "ugraph the playlist" stops at transcripts and looks broken. Re-running ingest
    # with nothing new still synthesizes any pending sources for this channel.
    channel_slug = result.get("slug")
    _run_feed_pipeline(
        cfg,
        limit=args.limit,
        channel=channel_slug,
        skip_extract=getattr(args, "no_synthesize", False),
    )
    return 0


# ---------------------------------------------------------------------------
# capture (M0 copy-paste)
# ---------------------------------------------------------------------------

def _clipboard_text() -> str:
    import subprocess

    # Clipboard support is opportunistic. A headless Linux install should fall
    # back to paste + Ctrl+D, not crash because the macOS-only `pbpaste` binary
    # is absent.
    commands = [
        ["pbpaste"],
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"],
    ]
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return result.stdout
    return ""


def _add_person_flow(cfg, url: str, *, yes: bool = False,
                     name: str | None = None) -> int:
    """Resolve, preview, confirm, and write one person reference."""
    from dataclasses import replace
    from ugraph import person as person_mod

    try:
        person = person_mod.resolve(url)
    except (RuntimeError, person_mod.PersonResolutionError) as exc:
        sys.exit(f"ugraph: {exc}")
    if name:
        person = replace(person, name=name.strip())

    print(f"Detected: {person.name}"
          f"{f' ({person.handle})' if person.handle else ''}")
    print(f"  profile: {person.profile_url}")
    print(f"  source:  {person.source_title}")

    if not yes:
        if not sys.stdin.isatty():
            print("\nNothing written: confirmation needs a terminal.")
            print(f"Run: ugraph person {url!r} --yes")
            return 1
        answer = input("Add this person to your knowledge base? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("Nothing written.")
            return 0

    result = person_mod.add(cfg, person)
    action = "Created" if result.created else "Already exists"
    print(f"{action}:")
    print(f"  canonical → {result.canonical_path}")
    print(f"  redirect  → {result.redirect_path}")
    return 0


def cmd_person(args) -> int:
    cfg = _config(args)
    url = getattr(args, "url", None)
    if not url:
        url = _clipboard_text().strip()
        if not url:
            if not sys.stdin.isatty():
                sys.exit("ugraph: no URL supplied")
            url = input("Paste a YouTube link: ").strip()
    return _add_person_flow(
        cfg, url, yes=getattr(args, "yes", False),
        name=getattr(args, "name", None),
    )


def cmd_embed(args) -> int:
    """Local Mac embeddings + paper §3.2 hash reuse (see `ugraph embed --bench`)."""
    from ugraph import embed as embed_mod

    cfg = _config(args)
    try:
        encoder = embed_mod.resolve_encoder(
            model=args.model,
            host=args.host,
            fake=args.fake,
            fake_delay_ms=args.fake_delay_ms,
        )
    except embed_mod.EmbedError as exc:
        sys.exit(f"ugraph: {exc}")

    if args.bench:
        print("ugraph embed --bench  (omni-macos §3.2 reuse across edits)")
        print("  indexing a synthetic doc, then re-indexing after append / mid-file insert")
        print("  reuse OFF = re-encode every chunk; reuse ON = skip matching hashes")
        print()
        try:
            report = embed_mod.run_reuse_bench(
                cfg, encoder=encoder, chunks=args.chunks
            )
        except embed_mod.EmbedError as exc:
            sys.exit(f"ugraph: {exc}")
        print(report.as_table())
        print()
        print("Vectors are derived state under <kb>/.ugraph/vectors/ — wipe anytime.")
        return 0

    slugs = [args.slug] if args.slug else None
    try:
        results = embed_mod.embed_all(
            cfg, encoder=encoder, reuse=not args.no_reuse, slugs=slugs
        )
    except embed_mod.EmbedError as exc:
        sys.exit(f"ugraph: {exc}")

    for r in results:
        mode = "reuse" if r.reuse else "no-reuse"
        print(
            f"{r.slug}: {r.encoded} encoded, {r.reused} reused, "
            f"{r.removed} removed  ({r.total} chunks, {r.seconds:.2f}s, {mode}, "
            f"{r.model} {r.dim}d)"
        )
    return 0


def _confirm_ingest(prompt: str, *, yes: bool) -> bool:
    """Ask before writing. TTY defaults to yes on empty Enter; non-TTY needs --yes."""
    if yes:
        return True
    if not sys.stdin.isatty():
        print("Nothing written: confirmation needs a terminal (or pass --yes).")
        return False
    answer = input(f"{prompt} ").strip().lower()
    if answer not in ("", "y", "yes"):
        print("Nothing written.")
        return False
    return True


def cmd_capture(args) -> int:
    cfg = _config(args)
    from ugraph import capture_intent
    from ugraph import ingest as ingest_mod

    clipboard = getattr(args, "clipboard", False)
    source_note = ""
    if not clipboard and sys.stdin.isatty():
        # Bare `ugraph` / `ugraph capture` at a terminal: the daily flow is
        # copy → preview → confirm → act.
        clip = _clipboard_text()
        if clip.strip():
            source_note = "(from clipboard)"
            text = clip
        else:
            print("Paste content, then Ctrl+D:", file=sys.stderr)
            text = sys.stdin.read()
            source_note = "(from paste)"
    elif clipboard:
        try:
            text = _clipboard_text()
        except Exception as exc:  # pragma: no cover
            sys.exit(f"ugraph: clipboard read failed: {exc}")
        source_note = "(from clipboard)"
    else:
        text = sys.stdin.read()
        source_note = "(from stdin)"

    if not text.strip():
        sys.exit("ugraph: nothing to capture (no input text)")

    intent = capture_intent.classify(text)
    print(capture_intent.format_preview(intent))
    if source_note:
        print(f"  {source_note}")

    # Piped stdin (scripts/CI): act without a prompt. Interactive TTY: confirm.
    # Explicit --yes always skips the prompt.
    auto = getattr(args, "yes", False) or (
        not sys.stdin.isatty() and not clipboard
        and source_note == "(from stdin)"
    )
    if not auto:
        if not _confirm_ingest(intent.confirm_prompt, yes=False):
            return 0 if sys.stdin.isatty() else 1

    if intent.kind in {"youtube_playlist", "youtube_feed"}:
        print(f"({intent.label} — running ingest → synthesize → concepts)")
        ns = argparse.Namespace(
            kb=getattr(args, "kb", None),
            source="youtube",
            url=intent.text,
            limit=getattr(args, "limit", None) or 10,
            newest=None,
            slug=None,
            dry_run=False,
            sleep=1.5,
            force=False,
            retry_failed=False,
            repair_state=False,
            synthesize=True,
            no_synthesize=False,
        )
        return cmd_ingest(ns)

    if intent.kind == "youtube_person":
        # Already confirmed at capture level — skip the second person prompt.
        return _add_person_flow(cfg, intent.text, yes=True)

    title = getattr(args, "title", None)
    slug = getattr(args, "slug", None)
    if slug is None:
        title = title or ingest_mod.derive_title(intent.text)
        slug = ingest_mod.unique_slug(cfg, title)

    source_uri = (
        "clipboard" if "clipboard" in source_note
        else "stdin" if "stdin" in source_note or "paste" in source_note
        else "stdin"
    )
    result = ingest_mod.capture_text(
        cfg, intent.text, title=title or slug, slug=slug, source_uri=source_uri,
        source_type="copy-paste",
    )
    print(f"Captured {result.slug}: {result.written} new, {result.skipped} skipped "
          f"({result.total_chunks} chunk(s))")
    print(f"  → {result.raw_path}")
    print(f"  → {cfg.sources / f'{result.slug}.md'}")

    from ugraph import indexes
    changed = indexes.write_all(cfg)
    if changed:
        print(f"  indexes refreshed ({len(changed)} file(s))")

    _maybe_synthesize(cfg, result.slug)
    return 0


def _maybe_synthesize(cfg, slug: str) -> None:
    """Auto Phase A after capture when a backend is configured.

    Synthesis is opt-in infrastructure, not a surprise: with no backend configured we
    say so once and stop. With one, every quote is gated against the chunks before
    anything is written, so a weak model costs retries, not trust.
    """
    from ugraph import extract as extract_mod
    from ugraph import promote as promote_mod

    backend = extract_mod.resolve_backend(cfg)
    if backend is None:
        print("  (synthesis skipped — no model configured; run `ugraph auth status`)")
        return

    model = getattr(backend, "model", "")
    print(f"  synthesizing with {backend.name} ({model})…")
    res = extract_mod.extract_document(cfg, slug, backend)
    if not res.written:
        print(f"  synthesis failed: {res.error}")
        if "401" in res.error or "AuthenticationError" in res.error:
            print(f"  → the {getattr(backend, 'provider', '')} key was rejected. "
                  "Fix it with `ugraph auth set <provider>`, or switch with "
                  "`ugraph auth use openai` / `ugraph auth use ollama`")
        elif "credit" in res.error.lower() or "insufficient_quota" in res.error:
            print(f"  → key is valid but the {getattr(backend, 'provider', '')} account "
                  "has no credits. Top up billing, or `ugraph auth use ollama` "
                  "to run locally for free.")
        return

    print(f"  extracted {res.concepts} concept(s), {len(res.rejected)} rejected by "
          f"the verbatim gate (attempt {res.attempts})")
    out = cfg.candidates / f"{slug}.json"
    try:
        import json as _json
        data = _json.loads(out.read_text(encoding="utf-8"))
        for c in data.get("concepts", []):
            anchor = str(c.get("anchor", ""))[:8]
            print(f"    • {c.get('name')}: {str(c.get('claim', ''))[:72]}  [{anchor}]")
    except Exception:
        pass
    print(f"  → {out}")

    promoted = promote_mod.promote_candidate_file(cfg, out)
    if promoted.written:
        print(f"  promoted {promoted.written} draft concept(s)")
        for path in promoted.paths[:12]:
            print(f"    • {path.relative_to(cfg.kb)}")
        from ugraph import indexes
        changed = indexes.write_all(cfg)
        if changed:
            print(f"  indexes refreshed ({len(changed)} file(s))")


def _run_feed_pipeline(cfg, *, limit: int, channel: str | None,
                       skip_extract: bool = False) -> None:
    """After YouTube ingest: Phase A extract → draft concepts → index.

    This is the feed counterpart to capture's `_maybe_synthesize`. The tool owns
    the pipeline; the user should not have to chain subcommands by hand.
    """
    from ugraph import extract as extract_mod
    from ugraph import indexes
    from ugraph import promote as promote_mod

    if skip_extract:
        print("  (synthesis skipped — --no-synthesize)")
        return

    backend = extract_mod.resolve_backend(cfg)
    if backend is None:
        print("  (synthesis skipped — no model configured; run `ugraph auth status`)")
        return

    model = getattr(backend, "model", "")
    provider = getattr(backend, "provider", "")
    label = f"{backend.name}/{provider}" if provider else backend.name
    print(f"\nSynthesizing with {label} ({model})…")

    def progress(i, total, slug, title):
        print(f"  [{i}/{total}] {title[:62]}")

    result = extract_mod.run(
        cfg, backend, limit=limit, progress=progress, channel=channel,
    )
    print(f"  extracted {result['written']}/{result['attempted']} "
          f"→ {result['concepts']} candidate concept(s)")
    if result["rejected"]:
        print(f"  {result['rejected']} candidate(s) rejected by the verbatim gate")
    for failure in result["failed"]:
        err = failure["error"]
        print(f"  FAILED {failure['slug']}: {err}")
        low = err.lower()
        if "credit" in low or "insufficient_quota" in low or "balance" in low:
            print("  → API key is valid but the account has no credits.")
            print("     Top up Anthropic/OpenAI billing, or: ugraph auth use ollama")
            break
    if result.get("aborted"):
        print("  Batch stopped after a billing/auth failure "
              "(remaining sources were not attempted).")
        print(f"  Resume:  {result.get('resume')}")

    promoted = promote_mod.promote_pending(cfg, channel=channel, limit=None)
    print(f"  promoted {promoted.written} draft concept page(s)"
          f" ({promoted.skipped_existing} already existed)")
    for path in promoted.paths[:20]:
        print(f"    • {path.relative_to(cfg.kb)}")
    if len(promoted.paths) > 20:
        print(f"    … +{len(promoted.paths) - 20} more")

    changed = indexes.write_all(cfg)
    if changed:
        print(f"  indexes refreshed ({len(changed)} file(s))")
    if result.get("aborted"):
        print("Pipeline paused: fix billing/auth, then resume with the command above")
    elif result["written"] == 0 and result["attempted"] and result["failed"]:
        print("Pipeline incomplete: extract failed — pending sources were not synthesized")
    else:
        print("Pipeline done: raw → candidates → draft concepts → indexes")


# ---------------------------------------------------------------------------
# auth — model backends and API keys
# ---------------------------------------------------------------------------

def cmd_auth(args) -> int:
    from ugraph import auth as auth_mod

    if args.action == "set":
        if args.provider not in auth_mod.PROVIDERS:
            sys.exit(f"ugraph: `auth set` expects one of {auth_mod.PROVIDERS}")
        import getpass
        key = getpass.getpass(f"{args.provider} API key (hidden): ")
        if not key.strip():
            sys.exit("ugraph: empty key — nothing saved")
        path = auth_mod.set_key(args.provider, key)
        print(f"saved {args.provider} key → {path} (permissions 0600)")
        if not auth_mod.get_backend().get("backend"):
            auth_mod.set_backend("api")
            print("default backend set to 'api' (change with `ugraph auth use ollama`)")
        return 0

    if args.action == "use":
        if args.provider in auth_mod.PROVIDERS:
            # `auth use openai` pins the provider within the api backend — the
            # escape hatch when one key is bad but the other works.
            auth_mod.set_backend("api", args.model, provider=args.provider)
            model_note = f" (model: {args.model})" if args.model else ""
            print(f"default backend: api, provider: {args.provider}{model_note}")
            return 0
        if args.provider not in ("api", "ollama"):
            sys.exit("ugraph: `auth use` expects 'api', 'ollama', 'anthropic' or 'openai'")
        auth_mod.set_backend(args.provider, args.model)
        model_note = f" (model: {args.model})" if args.model else ""
        print(f"default backend: {args.provider}{model_note}")
        return 0

    # status
    st = auth_mod.status()
    print("ugraph auth status")
    print(f"  config dir: {st['config_dir']}")
    for provider, source in st["keys"].items():
        print(f"  {provider:10} key: {source or 'not set'}")
    backend = st["backend"].get("backend")
    print(f"  default backend: {backend or 'auto (api if a key exists, else ollama)'}"
          + (f", model: {st['backend'].get('model')}" if st["backend"].get("model") else ""))

    from ugraph import extract as extract_mod
    try:
        extract_mod.OllamaBackend().check()
        print("  ollama:     reachable at localhost:11434")
    except extract_mod.BackendError:
        print("  ollama:     not reachable (install/start it, or set an API key)")

    print("\nNext:")
    if not any(st["keys"].values()):
        print("  ugraph auth set anthropic   # or: openai")
    else:
        print("  ugraph            # capture now auto-synthesizes")
        print("  ugraph auth use ollama   # switch to local models")
    return 0


# ---------------------------------------------------------------------------
# ps / logs — live observability over runs.jsonl
# ---------------------------------------------------------------------------

def _fmt_elapsed(ms: int | None) -> str:
    if not ms:
        return "00:00"
    total = max(0, int(ms) // 1000)
    return f"{total // 60:02d}:{total % 60:02d}"


def _render_ps(rows: list[dict]) -> None:
    active = sum(1 for r in rows if r.get("active"))
    print(f"{'MODULE':<9} {'SLUG':<30} {'STEP':<12} {'ELAPSED':<8} "
          f"{'BACKEND/MODEL':<26} STATUS")
    for row in rows:
        backend = row.get("backend", "")
        model = row.get("model", "")
        engine = f"{backend}/{model}" if model else backend
        if row.get("active"):
            status = "active"
        elif row.get("stale"):
            status = "stale (killed)"
        else:
            status = row.get("event", "?")
        print(f"{row.get('module', '?'):<9} "
              f"{str(row.get('slug', '-'))[:30]:<30} "
              f"{str(row.get('step', row.get('event', '')))[:12]:<12} "
              f"{_fmt_elapsed(row.get('elapsed_ms')):<8} "
              f"{engine[:26]:<26} {status}")
    print(f"\n{len(rows)} run(s) · {active} active")


def cmd_ps(args) -> int:
    cfg = _config(args)
    from ugraph import runs as runs_mod

    def once() -> None:
        rows = runs_mod.latest_per_run(cfg)[: args.limit]
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
        else:
            _render_ps(rows)

    if args.watch is None:
        once()
        return 0

    interval = args.watch or 2
    try:
        while True:
            print("\033[2J\033[H", end="")
            once()
            print(f"\n(refreshing every {interval}s — Ctrl+C to stop)")
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def cmd_logs(args) -> int:
    cfg = _config(args)
    from ugraph import runs as runs_mod

    events = (runs_mod.for_slug(cfg, args.slug, limit=args.limit)
              if args.slug else runs_mod.read(cfg, limit=args.limit))
    if args.json:
        print(json.dumps(events, indent=2, default=str))
        return 0

    skip = {"ts", "run", "module", "event", "slug", "elapsed_ms", "step"}
    for event in events:
        stamp = str(event.get("ts", ""))[11:19]
        step = event.get("step") or event.get("event", "")
        detail = " ".join(
            f"{k}={str(v)[:60]}" for k, v in event.items() if k not in skip
        )
        elapsed = _fmt_elapsed(event.get("elapsed_ms"))
        print(f"{stamp} {event.get('module', '?'):<8} {step:<12} {elapsed:>7}  {detail}")
    if not events:
        print("no runs recorded yet — events appear here after your next ugraph run")
    return 0


# ---------------------------------------------------------------------------
# index / lint / verify / status
# ---------------------------------------------------------------------------

def cmd_index(args) -> int:
    from ugraph import indexes
    cfg = _config(args)
    if args.check:
        stale = indexes.check(cfg)
        if stale:
            print("Stale indexes (run `ugraph index`):")
            for p in stale:
                print(f"  {p.relative_to(cfg.kb)}")
            return 1
        print("All indexes up to date.")
        return 0
    written = indexes.write_all(cfg)
    if written:
        print(f"Rebuilt {len(written)} index file(s):")
        for p in written:
            print(f"  {p.relative_to(cfg.kb)}")
    else:
        print("All indexes already current.")
    return 0


def cmd_lint(args) -> int:
    from ugraph import lint as lint_mod
    cfg = _config(args)
    findings, pages = lint_mod.lint(cfg)

    if args.json:
        print(json.dumps({
            "status": "fail" if findings.errors else "pass",
            "pages": len(pages),
            "errors": findings.errors,
            "warnings": findings.warnings,
        }, indent=2))
    else:
        for item in findings.errors:
            print(f"ERROR  [{item['check']}] {item['file']}: {item['message']}")
        if not args.quiet:
            for item in findings.warnings:
                print(f"WARN   [{item['check']}] {item['file']}: {item['message']}")
        verdict = "FAIL" if findings.errors else "PASS"
        print(f"\n{verdict} — {len(pages)} pages, "
              f"{len(findings.errors)} error(s), {len(findings.warnings)} warning(s)")

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(lint_mod.render_report(findings, pages), encoding="utf-8")
        print(f"Report written to {out}")

    return 1 if findings.errors or (args.warnings and findings.warnings) else 0


def cmd_verify(args) -> int:
    from ugraph import verify as verify_mod
    cfg = _config(args)

    if args.pages_only:
        issues = verify_mod.verify_pages(cfg)
    elif args.candidates_only:
        issues = verify_mod.verify_candidates(cfg)
    else:
        issues = verify_mod.verify(cfg)

    if args.json:
        print(json.dumps([i.__dict__ for i in issues], indent=2))
        return 1 if issues else 0

    for issue in issues:
        print(f"{issue.kind.upper():<20} {issue.file}")
        print(f"  @{issue.timestamp}  {issue.detail}")
        if issue.quote:
            print(f"  quote: {issue.quote}")
    if issues:
        print(f"\nFAIL — {len(issues)} quote/timestamp issue(s)")
        return 1
    print("PASS — every quote is verbatim and every timestamp resolves.")
    return 0


def cmd_status(args) -> int:
    from ugraph import status as status_mod
    cfg = _config(args)
    stats = status_mod.collect(cfg, **selectors(args))
    if args.json:
        print(json.dumps(stats, indent=2, default=str))
        return 0
    print(status_mod.render(stats, clusters=args.clusters,
                            pending=args.pending, thin=args.thin))
    return 0


def cmd_graph(args) -> int:
    from ugraph import graph as graph_mod
    cfg = _config(args)
    types = {"concept", "entity", "moc"} if args.concepts_only else None
    g = graph_mod.build(cfg, include_provenance=not args.no_provenance, types=types)
    try:
        if args.format == "d3":
            rendered = graph_mod.to_d3(g)
        else:
            rendered = graph_mod.render(g, args.format, config=cfg)
    except ValueError as exc:
        sys.exit(f"ugraph: {exc}")

    if args.format == "canvas" and graph_mod.find_vault_root(cfg) is None:
        print("  [warn] no .obsidian found above the KB — canvas file paths may not "
              "resolve. Open the .canvas from inside your vault.", file=sys.stderr)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        print(f"{len(g['nodes'])} nodes, {len(g['edges'])} edges → {out}")
    else:
        print(rendered)
    return 0



def cmd_ledger(args) -> int:
    from ugraph import ledger as ledger_mod
    cfg = _config(args)

    if args.action == "record":
        try:
            if not args.rec_slug or not args.rec_stage:
                sys.exit("ugraph: usage — ugraph ledger record <slug> <stage>")
            entry = ledger_mod.record(cfg, args.rec_slug, args.rec_stage,
                                      by=args.by, detail=args.detail)
        except ValueError as exc:
            sys.exit(f"ugraph: {exc}")
        print(f"recorded {entry['stage']}  {entry['slug']}")
        return 0

    if args.slug:
        events = ledger_mod.history(cfg, args.slug)
        if not events:
            print(f"no recorded transitions for {args.slug}")
            print("  (state is still derived from the files — try `ugraph ledger --json`)")
            return 0
        for e in events:
            detail = f"  {e['detail']}" if e.get("detail") else ""
            print(f"  {e['ts']}  {e['stage']:<13} {e.get('by', ''):<22}{detail}")
        return 0

    from ugraph import select

    items = ledger_mod.collect(cfg)
    sel = selectors(args)
    if any(v is not None for v in sel.values()):
        items = select.by_recency(items, **sel)
    if args.pending:
        items = [i for i in items if not i.done]
    if args.stuck is not None:
        # --stuck re-sorts by how long something has sat, which is the point of it.
        # That deliberately overrides publication order when both are given.
        items = [i for i in items if i.stuck and (i.age_days or 0) >= args.stuck]
        items.sort(key=lambda i: -(i.age_days or 0))

    if args.write:
        # The report is always the full ledger; a filtered view would be a report
        # about a filter. Count what was written, not what the flags selected —
        # "3 sources → ledger.md" on a file holding 150 is a lie about the artefact.
        everything = ledger_mod.collect(cfg)
        path = ledger_mod.write_report(cfg, everything)
        if args.json:
            print(json.dumps({"path": str(path), "sources": len(everything)}, indent=2))
        else:
            print(f"{len(everything)} sources → {path}")
        return 0

    if args.json:
        print(ledger_mod.to_json(items))
        return 0

    print(ledger_mod.render_table(items, limit=args.limit))
    return 0



def cmd_extract(args) -> int:
    from ugraph import extract as extract_mod
    from ugraph import select
    cfg = _config(args)

    settings = cfg.raw.get("extract", {}) or {}
    backend_name = args.backend or settings.get("backend") or "claude-code"
    model = args.model or settings.get("model")
    sel = selectors(args)

    # `--dry-run` exists because selection used to be invisible: `--limit 10` silently
    # meant "ten talks whose slug starts with a". Being able to see the batch, in
    # order, before spending an hour of local inference is worth one flag.
    if args.dry_run:
        batch = extract_mod.pending_sources(cfg, **sel)[:args.limit]
        if args.json:
            print(json.dumps([{
                "slug": str(p.meta.get("slug") or p.id),
                "published": p.meta.get("published"),
                "title": p.title,
            } for p in batch], indent=2))
            return 0
        phrase = select.describe(**sel)
        print(f"{len(batch)} source(s) would be extracted"
              + (f" ({phrase})" if phrase else "") + ":")
        for page in batch:
            date_str = str(page.meta.get("published") or "undated")
            print(f"  {date_str:<12} {page.title[:58]}")
        return 0

    # claude-code is not something this process can drive — the agent does the work.
    # Say so plainly rather than pretending to dispatch it.
    if backend_name == "claude-code":
        pending = extract_mod.pending_sources(cfg, **sel)
        print(f"{len(pending)} source(s) waiting to be extracted.")
        print()
        print("The claude-code backend runs in your agent, not here:")
        print("    ugraph skills install")
        print("    then in Claude Code:  /channel-to-kb")
        print()
        print("To have ugraph do the extraction itself instead:")
        print("    ugraph extract --backend ollama    # local, free")
        print("    ugraph extract --backend api       # ANTHROPIC_API_KEY / OPENAI_API_KEY")
        return 0

    try:
        backend = extract_mod.make_backend(backend_name, model)
    except extract_mod.BackendError as exc:
        sys.exit(f"ugraph: {exc}")

    def progress(i, total, slug, title):
        print(f"[{i}/{total}] {title[:62]}")

    result = extract_mod.run(cfg, backend, limit=args.limit, progress=progress, **sel)

    if args.json:
        payload = {k: v for k, v in result.items() if k != "results"}
        print(json.dumps(payload, indent=2))
        return 1 if result["failed"] else 0

    print()
    print(f"Extracted {result['written']}/{result['attempted']} "
          f"→ {result['concepts']} candidate concepts")
    if result["rejected"]:
        # Not a warning about the KB — a measurement of the model. The gate did its job.
        print(f"  {result['rejected']} candidate(s) rejected as not verbatim")
    for failure in result["failed"]:
        err = failure["error"]
        print(f"  FAILED {failure['slug']}: {err}")
        low = err.lower()
        if "credit" in low or "insufficient_quota" in low or "balance" in low:
            print("  → API key is valid but the account has no credits.")
            print("     Top up Anthropic/OpenAI billing, or: ugraph auth use ollama")
            break
    if result.get("aborted"):
        print("Batch stopped after a billing/auth failure "
              "(remaining sources were not attempted).")
        print(f"Resume:  {result.get('resume')}")

    # Draft concept pages are the tool-owned half of Phase B. Cross-talk merge
    # still wants an agent; one-concept-per-candidate drafts do not.
    if result["written"]:
        from ugraph import indexes
        from ugraph import promote as promote_mod

        promoted = promote_mod.promote_pending(
            cfg, channel=sel.get("channel"), limit=None,
        )
        print(f"  promoted {promoted.written} draft concept page(s)"
              f" ({promoted.skipped_existing} already existed)")
        for path in promoted.paths[:20]:
            print(f"    • {path.relative_to(cfg.kb)}")
        changed = indexes.write_all(cfg)
        if changed:
            print(f"  indexes refreshed ({len(changed)} file(s))")
    return 1 if result["failed"] or result.get("aborted") else 0


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------

def cmd_skills(args) -> int:
    if args.action != "install":
        sys.exit("ugraph: only `ugraph skills install` is supported")
    src = _bundled("skills")
    dest = Path(args.dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for item in src.iterdir():
        target = dest / item.name
        if target.exists() and not args.force:
            print(f"  skip (exists): {target}")
            continue
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
        copied.append(target)
    for p in copied:
        print(f"  installed: {p}")
    print(f"\n{len(copied)} skill(s) installed to {dest}")
    print("In Claude Code, run:  /channel-to-kb")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def add_selectors(sp, since: bool = True, channel: bool = True) -> None:
    """The recency flags, added from one place so they cannot drift apart.

    `--newest` meaning "most recently published" in `extract` and something subtly
    different in `ledger` would be worse than not offering it at all.
    """
    sp.add_argument("--newest", type=int, metavar="N",
                    help="the N most recently published")
    if since:
        sp.add_argument("--since", metavar="DATE",
                        help="published on or after DATE (YYYY-MM-DD, or 7d/2w/3m/1y)")
    if channel:
        sp.add_argument("--channel", metavar="SLUG",
                        help="restrict to one channel, e.g. ai-engineer")


def selectors(args) -> dict:
    """Resolve the selector flags into kwargs, exiting cleanly on a bad date."""
    from ugraph import select

    raw = getattr(args, "since", None)
    try:
        since = select.parse_since(raw) if raw else None
    except ValueError as exc:
        sys.exit(f"ugraph: {exc}")
    return {"newest": getattr(args, "newest", None), "since": since,
            "channel": getattr(args, "channel", None)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ugraph",
        description=(
            "Build an agent-navigable knowledge base from clipboard, files, "
            "and YouTube feeds — with verified quotes."
        ),
    )
    p.add_argument("--version", action="version", version=f"ugraph-kit {__version__}")
    p.add_argument("--kb", metavar="PATH",
                   help="knowledge base root (default: ugraph.toml, $UGRAPH_KB, or cwd)")
    p.add_argument("--yes", "-y", action="store_true",
                   help="skip the ingest confirmation prompt (bare ugraph / capture)")
    # Bare `ugraph` is the daily capture flow: copy → preview → confirm → act.
    p.set_defaults(func=cmd_capture)
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("init", help="scaffold a new knowledge base")
    sp.add_argument("path", nargs="?",
                    help="where to create it; omit for the interactive setup")
    sp.add_argument("--force", action="store_true", help="overwrite an existing scaffold")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("ingest", help="fetch source material")
    sp.add_argument("source", choices=["youtube", "file"])
    sp.add_argument("url")
    sp.add_argument("--limit", type=int, default=10, help="max NEW items this run")
    # No --since here: yt-dlp's flat playlist listing returns NA for upload_date, so a
    # date filter would need a per-video metadata fetch — most of the cost of ingesting
    # anyway. Listing order is the only cheap recency signal, hence --newest.
    sp.add_argument("--newest", type=int, metavar="N",
                    help="only consider the N most recent uploads, held or not")
    sp.add_argument("--slug", help="override the channel slug")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--sleep", type=float, default=1.5,
                    help="seconds between fetches; raise it if you hit rate limits")
    sp.add_argument("--force", action="store_true", help="re-fetch items already recorded")
    sp.add_argument("--retry-failed", action="store_true",
                    help="reconsider videos recorded as unfetchable")
    sp.add_argument("--repair-state", action="store_true",
                    help="drop ingested IDs with no raw transcript so missing "
                         "videos can be re-fetched (does not download)")
    sp.add_argument("--no-synthesize", action="store_true",
                    help="stop after transcripts; skip extract + draft concepts")
    sp.set_defaults(func=cmd_ingest, synthesize=False)

    sp = sub.add_parser("capture", help="ingest text from stdin or clipboard (M0)")
    sp.add_argument("--title", help="human title (defaults to slug)")
    sp.add_argument("--slug", help="document slug")
    sp.add_argument("--clipboard", action="store_true", help="read from clipboard instead of stdin")
    sp.add_argument("--yes", "-y", action="store_true",
                    help="skip the ingest confirmation prompt")
    sp.set_defaults(func=cmd_capture)

    sp = sub.add_parser(
        "embed",
        help="local embeddings with chunk-hash reuse (paper §3.2)",
    )
    sp.add_argument("--slug", help="embed one document; default: every ingested doc")
    sp.add_argument("--model", default=None,
                    help="Ollama embed model (default: nomic-embed-text)")
    sp.add_argument("--host", default=None, help="Ollama host (default: http://127.0.0.1:11434)")
    sp.add_argument("--no-reuse", action="store_true",
                    help="re-encode every chunk (ablation / forced refresh)")
    sp.add_argument("--bench", action="store_true",
                    help="compare reuse on vs off for append and mid-file edits")
    sp.add_argument("--chunks", type=int, default=16,
                    help="paragraphs in the --bench corpus (default: 16)")
    sp.add_argument("--fake", action="store_true",
                    help="use a deterministic fake encoder (no Ollama; for CI)")
    sp.add_argument("--fake-delay-ms", type=float, default=5.0,
                    help="per-chunk delay for --fake (default: 5)")
    sp.set_defaults(func=cmd_embed)

    sp = sub.add_parser(
        "person",
        help="resolve a person from a YouTube link and add them to the KB",
    )
    sp.add_argument(
        "url", nargs="?",
        help="video/channel/profile URL (defaults to clipboard)",
    )
    sp.add_argument("--name", help="override the resolved display name")
    sp.add_argument("--yes", "-y", action="store_true",
                    help="write without interactive confirmation")
    sp.set_defaults(func=cmd_person)

    sp = sub.add_parser("auth", help="configure model backends and API keys")
    sp.add_argument("action", choices=["set", "status", "use"], nargs="?", default="status")
    sp.add_argument("provider", nargs="?",
                    choices=["anthropic", "openai", "api", "ollama"])
    sp.add_argument("--model", help="model override for `auth use`")
    sp.set_defaults(func=cmd_auth)

    sp = sub.add_parser("ps", help="live view of running and recent jobs")
    sp.add_argument("--watch", "-w", type=int, nargs="?", const=2, metavar="SEC",
                    help="re-render every SEC seconds (default 2)")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_ps)

    sp = sub.add_parser("logs", help="event trail for one item, or recent runs")
    sp.add_argument("slug", nargs="?")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_logs)

    sp = sub.add_parser("index", help="regenerate every index.md")
    sp.add_argument("--check", action="store_true", help="exit 1 if stale; write nothing")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("lint", help="conformance gate")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--quiet", action="store_true", help="errors only")
    sp.add_argument("--warnings", action="store_true", help="treat warnings as failure")
    sp.add_argument("--report", metavar="PATH", help="also write a markdown report")
    sp.set_defaults(func=cmd_lint)

    sp = sub.add_parser("verify", help="every quote verbatim, every timestamp real")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--candidates-only", action="store_true")
    sp.add_argument("--pages-only", action="store_true")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("status", help="extraction progress and graph health")
    sp.add_argument("--clusters", action="store_true")
    sp.add_argument("--pending", action="store_true")
    sp.add_argument("--thin", action="store_true", help="single-source concepts")
    add_selectors(sp)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("graph", help="export the KB as a graph (derived view)")
    sp.add_argument("--format", default="json",
                    choices=["json", "graphml", "dot", "canvas", "obsidian-groups", "d3"],
                    help="canvas = Obsidian Canvas; d3 = standalone interactive HTML")
    sp.add_argument("--out", metavar="PATH", help="write to a file instead of stdout")
    sp.add_argument("--no-provenance", action="store_true",
                    help="drop concept→source edges; clearer for diagramming")
    sp.add_argument("--concepts-only", action="store_true",
                    help="concepts, entities and MOCs only — sources usually "
                         "outnumber them and swamp a visual")
    sp.set_defaults(func=cmd_graph)

    sp = sub.add_parser("ledger", help="lifecycle state of every source")
    sp.add_argument("action", nargs="?", choices=["record"], default=None,
                    help="`record` appends a transition; omit to view")
    sp.add_argument("rec_slug", nargs="?", metavar="SLUG",
                    help="source slug (with `record`)")
    sp.add_argument("rec_stage", nargs="?", metavar="STAGE",
                    help="stage name (with `record`)")
    sp.add_argument("--slug", help="show the recorded history of one source")
    sp.add_argument("--by", default="", help="what performed the transition")
    sp.add_argument("--detail", default="", help="free-text note")
    sp.add_argument("--pending", action="store_true", help="not yet complete")
    sp.add_argument("--stuck", type=int, metavar="DAYS", nargs="?", const=0,
                    help="pulled but unprocessed for DAYS+ days")
    sp.add_argument("--limit", type=int, default=40)
    add_selectors(sp)
    sp.add_argument("--write", action="store_true",
                    help="write a markdown report into the logs directory")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_ledger)

    sp = sub.add_parser("extract", help="model-driven candidate extraction (Phase A)")
    sp.add_argument("--backend", choices=["claude-code", "ollama", "api"],
                    help="default: [extract].backend in ugraph.toml, else claude-code")
    sp.add_argument("--model", help="override the backend's model")
    sp.add_argument("--limit", type=int, default=10, help="max sources this run")
    add_selectors(sp)
    sp.add_argument("--dry-run", action="store_true",
                    help="list what would be extracted, in order, and stop")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_extract)

    sp = sub.add_parser("skills", help="install the agent instructions")
    sp.add_argument("action", choices=["install"])
    sp.add_argument("--dest", default=".claude/skills")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_skills)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        # A downstream reader closed the pipe — `ugraph graph | head`, `| jq .nodes[0]`.
        # That is normal usage, not an error, but Python will also try to flush stdout
        # on exit and raise a second time. Pointing the fd at devnull first is the
        # documented way to exit quietly.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 141  # 128 + SIGPIPE, what a shell expects


if __name__ == "__main__":
    raise SystemExit(main())
