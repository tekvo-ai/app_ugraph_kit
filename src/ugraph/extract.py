"""
extract.py — optional model-driven candidate extraction (Phase A).

`ugraph` itself calls no model. This module is the one place that can, and it is opt-in:
the deterministic core keeps its three dependencies, and anything here is an extra.

## What this does and does not do

It does **Phase A only** — reading one transcript and emitting candidate concepts with
verbatim quotes and timestamps. That is mechanical work: find the claims, copy the words
exactly, note the time.

It deliberately does **not** do Phase B (deciding which candidates merge into which
canonical page). That decision needs every candidate in view at once and it is where the
entire value of the format lives — ten talks about one idea becoming one page rather than
ten. There is also no mechanical check for getting it wrong, which is precisely why it
deserves a good model and a human in the loop rather than a batch job.

## Why a weak model is safe here

Every quote a model produces is checked against the transcript before it is written:
a `verbatim_quote` that is not a literal substring is rejected and retried, and a
timestamp that does not exist is rejected. A 7B model that paraphrases gets caught by a
substring test, not by trust.

That turns an unreliable generator into a reliable pipeline at the cost of retries — the
`generation-verification loop`, applied to the tool that builds knowledge bases about it.

Backends:
    claude-code  guidance only; the agent does the work via the installed skill
    ollama       local, free, private. No new dependency — plain HTTP.
    api          Anthropic or OpenAI. Needs the `[api]` extra and a key.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ugraph import ledger, runs, select, templates
from ugraph.config import Config
from ugraph.model import Page, iter_pages
from ugraph.store import read_md

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Retries per transcript when the verbatim gate rejects the output. Two is enough to
# clear transient sloppiness; a model that fails three times is the wrong model.
MAX_ATTEMPTS = 3

ProgressFn = Callable[[int, int, str, str], None]

#: Rough chars-per-token for English prose. Only used to size the context window, where
#: being wrong by 20% costs a little memory and being wrong the other way costs the
#: entire run — so it deliberately over-estimates.
CHARS_PER_TOKEN = 3.0

#: Smallest context worth requesting, and the ceiling we will ask a local model for.
#: Above ~32k most consumer machines start swapping, which is slower than failing.
MIN_CONTEXT = 8192
MAX_CONTEXT = 32768

#: The shape Phase A must return, handed to the backend as a constraint rather than a
#: request. `verbatim_quote` and `timestamp` are what the gate checks; without them a
#: concept cannot be verified and is not worth keeping.
CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "yield": {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "claim": {"type": "string"},
                    "verbatim_quote": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "domain": {"type": "string"},
                },
                "required": ["name", "claim", "verbatim_quote", "timestamp"],
            },
        },
    },
    "required": ["yield", "concepts"],
}


def context_for(system: str, user: str) -> int:
    """A context window big enough for this prompt plus room to answer.

    Ollama silently truncates rather than erroring, so guessing low does not fail
    loudly — it produces confident nonsense. Round up generously.
    """
    prompt = (len(system) + len(user)) / CHARS_PER_TOKEN
    needed = int(prompt + 2048)  # headroom for the JSON coming back
    size = MIN_CONTEXT
    while size < needed and size < MAX_CONTEXT:
        size *= 2
    return min(size, MAX_CONTEXT)


def auth_provider_for(model):
    """`auth.provider_for_model`, imported here so `check()` stays lazy."""
    from ugraph import auth

    return auth.provider_for_model(model)


def _as_int(value):
    """A positive int from a config value, or None. Never raises on bad input."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value):
    text = str(value).strip() if value is not None else ""
    return text or None


class BackendError(RuntimeError):
    """Raised when a backend cannot run at all — missing key, server down."""


@dataclass
class ExtractResult:
    slug: str
    written: bool = False
    concepts: int = 0
    attempts: int = 0
    rejected: list[str] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class Backend:
    name = "base"

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def check(self) -> None:
        """Raise BackendError with an actionable message if unusable."""


class OllamaBackend(Backend):
    """Local models over Ollama's HTTP API.

    Uses urllib rather than a client library so the core install stays dependency-free —
    a local backend that requires a pip extra defeats the point of being local.
    """

    name = "ollama"

    def __init__(self, model: str = "qwen2.5-coder:7b", url: str = OLLAMA_URL):
        self.model = model
        self.url = url.rstrip("/")

    def check(self) -> None:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=5) as resp:
                tags = json.loads(resp.read())
        except Exception as exc:
            raise BackendError(
                f"cannot reach Ollama at {self.url} ({exc}).\n"
                "  Start it with `ollama serve`, or install from https://ollama.com"
            ) from exc

        available = {m.get("name", "") for m in tags.get("models", [])}
        if self.model not in available and f"{self.model}:latest" not in available:
            listed = ", ".join(sorted(available)[:6]) or "none"
            raise BackendError(
                f"model {self.model!r} is not pulled. Available: {listed}\n"
                f"  Get it with:  ollama pull {self.model}"
            )

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "prompt": user,
            "system": system,
            "stream": False,
            # Force the shape rather than asking for it. Without this a 7B model
            # returns beautifully-formed JSON in a schema it made up, which parses
            # and then contains nothing the gate can check.
            "format": CANDIDATE_SCHEMA,
            "options": {
                # Deterministic-ish: this is extraction, not writing. Creativity
                # here means paraphrase, which the verbatim gate then rejects.
                "temperature": 0.1,
                # THE bug that made local extraction look broken. Ollama defaults
                # to a 4096-token context regardless of what the model supports.
                # A 12-minute talk overflows it, the prompt is truncated from the
                # front, the schema instructions are the first thing lost — and the
                # model, now with no spec, confidently invents its own format.
                # Silent, and it looks like the model is simply too weak.
                "num_ctx": context_for(system, user),
            },
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/api/generate", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=900) as resp:
            return json.loads(resp.read()).get("response", "")


class ApiBackend(Backend):
    """Anthropic or OpenAI. Imported lazily so the core install never needs them.

    Keys resolve through ugraph.auth: env var first, then ~/.config/ugraph/keys.toml
    (written by `ugraph auth set`). The key is passed to the client explicitly rather
    than relying on the SDK's env lookup, so a keys-file user and an env user get
    identical behavior.

    Token budgets are never hardcoded here. Anthropic requires an output ceiling, so
    one is resolved per request through `ugraph.limits` — operator config, then the
    provider's own model metadata, then a budget derived from the prompt. OpenAI does
    not require one, so the parameter is omitted and the provider applies the model's
    own maximum. Either way, changing `model` needs no change here.
    """

    name = "api"

    def __init__(self, model: str | None = None, config: Config | None = None):
        from ugraph import auth

        # The model decides the provider when it names one. Without this, a pinned
        # provider would send `gpt-4o` to Anthropic, which fails as an auth-looking
        # error and sends the user hunting for the wrong problem.
        routed = auth.provider_for_model(model)
        preferred = routed or auth.get_backend().get("provider")
        order = ([preferred] + [p for p in auth.PROVIDERS if p != preferred]
                 if preferred else list(auth.PROVIDERS))

        self.provider = ""
        self.api_key: str | None = None
        for candidate in order:
            key = auth.get_key(candidate)
            if key:
                self.provider, self.api_key = candidate, key
                break

        # A routed provider is not a preference, it is a requirement: falling back to
        # the other provider's key would silently run a different model than asked.
        if routed and self.provider != routed:
            self.provider, self.api_key = routed, None

        self.model = model or auth.default_model(self.provider)

        # Everything below is operator-tunable in ugraph.toml under [extract]. Each
        # one stays None unless set, so an unset knob means "provider default"
        # rather than a value this file invented.
        settings = (config.raw.get("extract", {}) if config else {})
        self.config_dir = auth.config_dir()
        self.max_tokens: int | None = _as_int(settings.get("max_tokens"))
        self.thinking: str | None = _as_str(settings.get("thinking"))
        self.effort: str | None = _as_str(settings.get("effort"))
        self.temperature: float | None = _as_float(settings.get("temperature"))

    def _client(self) -> Any:
        if self.provider == "anthropic":
            import anthropic

            return anthropic.Anthropic(api_key=self.api_key)
        import openai

        return openai.OpenAI(api_key=self.api_key)

    def output_budget(self, system: str, user: str, client: Any) -> int:
        """The `max_tokens` to request. Discovered or derived, never a literal."""
        from ugraph import limits as limits_mod

        found = limits_mod.resolve(
            self.provider, self.model,
            config_dir=self.config_dir, client=client, configured=self.max_tokens,
        )
        if found.max_output_tokens:
            return found.max_output_tokens
        return limits_mod.derive_output_budget(
            system, user, ceiling=found.max_input_tokens)

    def check(self) -> None:
        if not self.api_key:
            wanted = self.provider or "anthropic` or `openai"
            because = (f" — {self.model} is served by {self.provider}"
                       if self.provider and auth_provider_for(self.model) else "")
            raise BackendError(
                f"no {self.provider or 'API'} key found{because}.\n"
                f"  Run `ugraph auth set {wanted}`,\n"
                "  or use `--backend ollama` to run locally."
            )
        try:
            __import__(self.provider)
        except ImportError as exc:
            raise BackendError(
                f"the {self.provider} package is not installed.\n"
                f"  Install the extra:  pip install 'ugraph-kit[api]'"
            ) from exc

    def complete(self, system: str, user: str) -> str:
        client = self._client()
        if self.provider == "anthropic":
            return self._complete_anthropic(client, system, user)
        return self._complete_openai(client, system, user)

    def _complete_anthropic(self, client: Any, system: str, user: str) -> str:
        """Stream, always.

        Streaming is what lets the budget be generous: the SDK refuses a
        non-streaming request whose ceiling is large enough to risk an HTTP timeout,
        which is exactly the ceiling a current model reports. Billing is on tokens
        produced, not on the ceiling requested, so asking for the model's real limit
        costs nothing and removes truncation as a failure mode.
        """
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.output_budget(system, user, client),
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        # Passed through only when configured. On models where thinking is on by
        # default it draws on the same budget as the answer, which is the other
        # reason the ceiling above is discovered rather than fixed.
        if self.thinking:
            request["thinking"] = {"type": self.thinking}
        if self.effort:
            request["output_config"] = {"effort": self.effort}
        if self.temperature is not None:
            request["temperature"] = self.temperature

        with client.messages.stream(**request) as stream:
            message = stream.get_final_message()
        return "".join(b.text for b in message.content if b.type == "text")

    def _complete_openai(self, client: Any, system: str, user: str) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        # Omitted unless the operator set one: absent, the API applies the model's
        # own maximum, which is a better answer than any number this file could pick.
        if self.max_tokens:
            request["max_completion_tokens"] = self.max_tokens
        if self.temperature is not None:
            request["temperature"] = self.temperature

        message = client.chat.completions.create(**request)
        return message.choices[0].message.content or ""


BACKENDS = {"ollama": OllamaBackend, "api": ApiBackend}


def make_backend(name: str, model: str | None = None,
                 config: Config | None = None) -> Backend:
    """Build and check one backend.

    `config` is threaded through so a backend can read its own `[extract]` settings
    (token ceilings, thinking, effort) instead of carrying defaults in code. It stays
    optional: a caller that has no Config still gets a working backend on provider
    defaults.
    """
    if name not in BACKENDS:
        known = ", ".join(sorted(BACKENDS) + ["claude-code"])
        raise BackendError(f"unknown backend {name!r}; expected one of {known}")
    cls = BACKENDS[name]
    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model
    # Only ApiBackend reads config today; passing it to a backend that does not
    # accept it would be a TypeError, so ask rather than assume.
    if config is not None and "config" in inspect.signature(cls).parameters:
        kwargs["config"] = config
    backend = cls(**kwargs)
    backend.check()
    return backend


def resolve_backend(config: Config, requested: str | None = None,
                    model: str | None = None) -> Backend | None:
    """The backend a command should use, or None if nothing is configured.

    Order: explicit flag → [extract].backend in ugraph.toml → `ugraph auth use`
    preference → auto-detect (any API key, else a reachable Ollama). None means
    "not set up", which is a hint to print, not an error to raise.
    """
    from ugraph import auth

    model = model or config.raw.get("extract", {}).get("model") \
        or auth.get_backend().get("model")
    name = requested or config.raw.get("extract", {}).get("backend") \
        or auth.get_backend().get("backend") or ""

    if not name:
        # A model ID names its own backend. This is what lets `--model <anything>`
        # work with no other configuration: `claude-*`/`gpt-*` route to the API,
        # everything else is a local model, and a model released tomorrow needs no
        # code change to be routable.
        name = auth.backend_for_model(model) or ""

    if not name:
        if any(auth.get_key(p) for p in auth.PROVIDERS):
            name = "api"
        else:
            try:
                OllamaBackend().check()
                name = "ollama"
            except BackendError:
                return None
    if name == "claude-code":
        return None  # guidance-only backend: no programmatic run
    try:
        return make_backend(name, model, config=config)
    except BackendError:
        return None


# ---------------------------------------------------------------------------
# The verbatim gate
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_TIMESTAMP = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]", re.MULTILINE)


def _norm(text: str) -> str:
    return _WS.sub(" ", str(text)).strip()


def paragraphs(transcript: str) -> list[tuple[str, str]]:
    """[(marker, normalized text)] for each `[HH:MM:SS]` paragraph, in order."""
    parts = _TIMESTAMP.split(transcript)
    # split() yields [preamble, stamp, text, stamp, text, ...]
    return [(parts[i], _norm(parts[i + 1])) for i in range(1, len(parts) - 1, 2)]


def locate(quote: str, paras: Sequence[tuple[str, str]]) -> str | None:
    """The marker of the paragraph containing this quote, or None if it is in none.

    Checked against the paragraph the quote actually sits in rather than the whole
    transcript, because that is what `ugraph verify` enforces later. A gate that is
    weaker than the verifier writes files the verifier then rejects.
    """
    for marker, text in paras:
        if quote in text:
            return marker
    return None


def gate(candidate: dict, transcript: str) -> tuple[list[dict], list[str]]:
    """Keep only concepts whose quote survives checking, and fix their timestamps.

    This is what makes a small local model usable. A model that paraphrases produces a
    quote that is not a substring, and that is caught here rather than discovered
    months later in a page that cites something nobody said.

    Timestamps are **corrected, not judged**. If the quote is verbatim we know exactly
    which paragraph it came from, so a model that names the neighbouring marker — the
    actual observed failure, consistently off by one paragraph — has produced a good
    concept with a recoverable field, not a bad concept. Deriving the answer we can
    compute beats rejecting work over it.
    """
    paras = paragraphs(transcript)
    body = _norm(transcript)

    kept, rejected = [], []
    for concept in candidate.get("concepts") or []:
        name = str(concept.get("name", "?"))
        quote = _norm(concept.get("verbatim_quote", ""))

        if not quote:
            rejected.append(f"{name}: no quote")
            continue

        marker = locate(quote, paras)
        if marker is None:
            # Present in the transcript but spanning a paragraph boundary is still a
            # real quote; only text that appears nowhere is a fabrication.
            if quote not in body:
                rejected.append(f"{name}: quote is not verbatim")
                continue
            rejected.append(f"{name}: quote straddles two paragraphs, cannot cite one")
            continue

        concept["timestamp"] = marker
        kept.append(concept)

    return kept, rejected


def parse_json(text: str) -> dict | None:
    """Pull a JSON object out of a model response.

    Small models wrap JSON in prose or code fences however they were feeling. Rather
    than prompt harder, find the outermost braces — cheaper than a retry.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def pending_sources(config: Config, newest: int | None = None,
                    since: date | None = None,
                    channel: str | None = None) -> list[Page]:
    """Sources with a transcript, no candidates yet, and not already synthesized.

    Ordered newest-published first. `iter_pages` walks the filesystem alphabetically,
    which meant `extract --limit 10` reliably chose ten talks whose slug began with
    "a" — a batch selection that had nothing to do with what was worth reading next.
    """
    out = []
    for page in iter_pages(config, root=config.sources, strict=False):
        if page.type != "source":
            continue
        if str(page.meta.get("summary_status", "")) == "done":
            continue
        slug = str(page.meta.get("slug") or page.id)
        if (config.candidates / f"{Path(slug).name}.json").is_file():
            continue
        raw_ref = page.meta.get("raw")
        if raw_ref and (page.path.parent / str(raw_ref)).resolve().is_file():
            out.append(page)
    return select.by_recency(out, newest=newest, since=since, channel=channel)


def spec() -> str:
    """The Phase A instructions, read from the file the Claude Code skill also uses.

    Single source of truth on purpose: if the API backend and the agent skill drifted,
    two users of the same tool would get differently-shaped candidates from the same
    transcript, and Phase B would have to guess which convention it was reading.
    """
    return templates.read("channel-to-kb/references/candidate-extraction.md",
                          kind="skills")


# Provider failures that will not fix themselves mid-batch. Keep hammering the
# rest of `--limit` burns credits/quota for nothing — abort and let the user resume.
_HARD_PROVIDER_MARKERS = (
    "credit balance",
    "too low to access",
    "insufficient_quota",
    "invalid_api_key",
    "authentication_error",
    "permission_error",
    "billing",
    "unauthorized",
    "invalid x-api-key",
    "401",
    "403",
)


def is_hard_provider_failure(error: str | None) -> bool:
    if not error:
        return False
    low = error.lower()
    return any(marker in low for marker in _HARD_PROVIDER_MARKERS)


def extract_one(config: Config, page: Page, backend: Backend,
                system: str) -> ExtractResult:
    slug = str(page.meta.get("slug") or page.id)
    result = ExtractResult(slug=slug)

    raw_path = (page.path.parent / str(page.meta.get("raw"))).resolve()
    _, transcript = read_md(raw_path)

    user = (
        f"Transcript slug: {slug}\n"
        f"Title: {page.title}\n\n"
        "Return ONLY the JSON object described in the spec. No prose, no code fence.\n\n"
        f"--- TRANSCRIPT ---\n{transcript}"
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result.attempts = attempt
        try:
            raw = backend.complete(system, user)
        except Exception as exc:  # network, timeout, provider error
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        candidate = parse_json(raw)
        if candidate is None:
            result.error = "response was not JSON"
            continue

        # Well-formed JSON in the wrong shape is the failure that hurts, because it
        # looks like success: no `concepts` key means gate() sees nothing, keeps
        # nothing, rejects nothing, and writes a candidate file recording that this
        # talk contained no ideas. Retry instead of believing it.
        if not isinstance(candidate.get("concepts"), list):
            result.error = ("response had no 'concepts' list — the model answered in "
                            "its own schema")
            continue

        kept, rejected = gate(candidate, transcript)
        result.rejected = rejected

        # No concepts is a legitimate outcome — a sponsor pitch has nothing in it.
        # Retry only when the gate threw work away, which means the model paraphrased.
        if rejected and kept == [] and attempt < MAX_ATTEMPTS:
            continue

        candidate["concepts"] = kept
        candidate.setdefault("slug", slug)
        candidate.setdefault("title", page.title)
        if not kept:
            candidate.setdefault("yield", "none")

        out = config.candidates / f"{Path(slug).name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

        result.written = True
        result.concepts = len(kept)
        try:
            from ugraph import promote as promote_mod

            promote_mod.mark_source_extracted(config, slug)
        except Exception:
            pass
        # bookkeeping must not fail a successful extraction
        with contextlib.suppress(Exception):
            ledger.record(config, slug, "extracted", by=f"ugraph extract ({backend.name})",
                          detail=f"{len(kept)} concepts, {len(rejected)} rejected")
        return result

    result.error = result.error or "failed the verbatim gate on every attempt"
    return result


def run(config: Config, backend: Backend, limit: int = 10,
        progress: ProgressFn | None = None, newest: int | None = None,
        since: date | None = None, channel: str | None = None) -> dict[str, Any]:
    system = spec()
    # `limit` bounds the work, the selectors bound the window: `--newest 20 --limit 5`
    # is "of the 20 most recent, do 5". So selection happens first and limit last.
    batch = pending_sources(config, newest=newest, since=since, channel=channel)[:limit]

    results = []
    aborted = False
    abort_error: str | None = None
    for i, page in enumerate(batch, 1):
        slug = str(page.meta.get("slug") or page.id)
        if progress:
            progress(i, len(batch), slug, page.title)
        one = extract_one(config, page, backend, system)
        results.append(one)
        if not one.written and is_hard_provider_failure(one.error):
            aborted = True
            abort_error = one.error
            break

    resume_parts = ["ugraph extract"]
    if backend.name:
        resume_parts.append(f"--backend {backend.name}")
    if channel:
        resume_parts.append(f"--channel {channel}")
    resume_parts.append(f"--limit {limit}")

    return {
        "backend": backend.name,
        "attempted": len(results),
        "written": sum(1 for r in results if r.written),
        "concepts": sum(r.concepts for r in results),
        "rejected": sum(len(r.rejected) for r in results),
        "failed": [{"slug": r.slug, "error": r.error} for r in results if not r.written],
        "aborted": aborted,
        "abort_error": abort_error,
        "resume": " ".join(resume_parts),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Text documents (no timestamps) — anchors are content-addressed chunks
# ---------------------------------------------------------------------------
#
# Pasted text has no [HH:MM:SS] markers, so the transcript gate cannot run. But M0
# ingest already gives every paragraph a content-addressed chunk id, which is a
# *better* citation than a timestamp: it survives edits to other parts of the doc.
# The model never invents anchors — the gate derives them, same as timestamps.

TEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "yield": {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "claim": {"type": "string"},
                    "verbatim_quote": {"type": "string"},
                },
                "required": ["name", "claim", "verbatim_quote"],
            },
        },
    },
    "required": ["yield", "concepts"],
}


def gate_text(candidate: dict, chunks: Sequence[tuple[str, str]]) -> tuple[list[dict], list[str]]:
    """Keep concepts whose quote is verbatim in exactly one chunk; anchor them.

    `chunks` is [(chunk_id, normalized_text)]. A quote found in no chunk is a
    fabrication; found in two or more it cannot be cited to one place. Both are
    rejected — identical philosophy to the transcript gate.
    """
    kept, rejected = [], []
    for concept in candidate.get("concepts") or []:
        name = str(concept.get("name", "?"))
        quote = _norm(concept.get("verbatim_quote", ""))
        if not quote:
            rejected.append(f"{name}: no quote")
            continue
        hits = [cid for cid, text in chunks if quote in text]
        if not hits:
            rejected.append(f"{name}: quote is not verbatim")
            continue
        if len(hits) > 1:
            rejected.append(f"{name}: quote spans chunks, cannot cite one")
            continue
        concept["anchor"] = hits[0]
        kept.append(concept)
    return kept, rejected


def _dedupe_concepts(concepts: list[dict]) -> list[dict]:
    """Drop exact repeats — grouped extraction can surface the same concept
    with the same evidence from overlapping context in different groups."""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for c in concepts:
        key = (str(c.get("name", "")).strip().lower(),
               _norm(c.get("claim", "")), _norm(c.get("verbatim_quote", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def text_spec() -> str:
    return templates.read("channel-to-kb/references/candidate-extraction-text.md",
                          kind="skills")


# Documents larger than this are extracted chunk-group by chunk-group rather than
# in one call. Whole-document extraction doesn't scale on small local models:
# the JSON response for a dense 10KB article outgrows the context window mid-
# generation (observed: qwen2.5-coder:7b truncated at 4K+ output tokens after
# 22 min), the repair attempt re-hits the same wall, and the run burns ~40 min
# for a guaranteed failure. Small prompts keep responses well inside the window.
CHUNKED_DOC_CHARS = 5000
GROUP_CHARS = 3500


def _groups(chunk_pairs: list[tuple[str, str]],
            max_chars: int) -> list[list[tuple[str, str]]]:
    groups: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    size = 0
    for cid, text in chunk_pairs:
        if cur and size + len(text) > max_chars:
            groups.append(cur)
            cur, size = [], 0
        cur.append((cid, text))
        size += len(text)
    if cur:
        groups.append(cur)
    return groups


def extract_document(config: Config, slug: str, backend: Backend) -> ExtractResult:
    """Phase A for a pasted/captured text document (raw/<slug>.md)."""
    from ugraph import ingest as ingest_mod
    from ugraph import ledger as ledger_mod

    result = ExtractResult(slug=slug)
    raw_path = config.raw_dir / f"{slug}.md"
    if not raw_path.is_file():
        result.error = f"no raw document for slug {slug!r}"
        return result

    meta, body = read_md(raw_path)
    chunk_pairs = [
        (ingest_mod.content_id(block, slug), _norm(block))
        for block in ingest_mod.chunk_text(body)
    ]
    if not chunk_pairs:
        result.error = "document has no content"
        return result

    system = text_spec()
    total_chars = sum(len(text) for _, text in chunk_pairs)
    groups = ([chunk_pairs] if total_chars <= CHUNKED_DOC_CHARS
              else _groups(chunk_pairs, GROUP_CHARS))

    def build_user(group: list[tuple[str, str]]) -> str:
        numbered = "\n\n".join(
            f"--- CHUNK {cid} ---\n{text}" for cid, text in group
        )
        return (
            f"Document slug: {slug}\n"
            f"Title: {meta.get('title', slug)}\n\n"
            "Return ONLY the JSON object described in the spec. No prose, no code fence.\n\n"
            f"--- DOCUMENT ---\n{numbered}"
        )

    with runs.Run(config, "extract", slug, backend=backend.name,
                  model=getattr(backend, "model", "")) as run:
        concepts_all: list = []
        for gi, group in enumerate(groups, 1):
            user = build_user(group)
            for attempt in range(1, MAX_ATTEMPTS + 1):
                result.attempts += 1
                run.stage("attempt", attempt=attempt, group=gi, groups=len(groups))
                try:
                    raw = backend.complete(system, user)
                except Exception as exc:
                    result.error = f"{type(exc).__name__}: {exc}"
                    run.fail(result.error, attempt=attempt, group=gi)
                    return result

                candidate = parse_json(raw)
                if candidate is None:
                    result.error = "response was not JSON"
                    run.stage("parse-error", attempt=attempt, group=gi)
                    continue
                if not isinstance(candidate.get("concepts"), list):
                    result.error = ("response had no 'concepts' list — the model answered in "
                                    "its own schema")
                    run.stage("schema-error", attempt=attempt, group=gi)
                    continue

                concepts_all.extend(candidate["concepts"])
                break
            else:
                # One group failing shouldn't sink the whole document: the other
                # groups' concepts still gate and write. The run events record it.
                run.stage("group-failed", group=gi, groups=len(groups))

        if not concepts_all and result.error:
            run.fail(result.error, attempt=result.attempts)
            return result

        candidate = {"concepts": concepts_all}
        kept, rejected = gate_text(candidate, chunk_pairs)
        kept = _dedupe_concepts(kept)
        result.rejected = rejected
        run.stage("gate", kept=len(kept), rejected=len(rejected))

        candidate["concepts"] = kept
        candidate.setdefault("slug", slug)
        candidate.setdefault("title", meta.get("title", slug))
        candidate.setdefault("source_type", meta.get("source_type", "copy-paste"))
        if not kept:
            candidate.setdefault("yield", "none")

        out = config.candidates / f"{Path(slug).name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        run.stage("write", path=str(out), concepts=len(kept))

        result.written = True
        result.concepts = len(kept)
        # bookkeeping must not fail a successful extraction
        with contextlib.suppress(Exception):
            ledger_mod.record(config, slug, "extracted",
                              by=f"ugraph capture ({backend.name})",
                              detail=f"{len(kept)} concepts, {len(rejected)} rejected")
        return result
