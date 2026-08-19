"""
limits.py — what a model will actually accept, discovered rather than hardcoded.

A literal token budget written into a call site is wrong the moment the model changes,
and wrong in both directions: too low silently truncates the answer mid-JSON, too high
is rejected outright. So nothing here ships a token count for a named model.

Limits are resolved in this order, most authoritative first:

    1. the operator's `[extract].max_tokens` — an explicit ceiling always wins;
    2. the provider's own model metadata, cached on disk so the lookup costs one
       request per model per day;
    3. a budget derived from the prompt, for when the provider cannot be reached.

Step 3 is why this module has no per-model numbers. The answer to an extraction is a
bounded JSON structure whose size tracks the input — more source text means more
candidate concepts — so the budget is a function of the prompt, exactly as
`extract.context_for` already sizes Ollama's context window from the same input.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CACHE_FILENAME = "model_limits.json"

#: How long a discovered limit stays fresh. Model ceilings change on release
#: boundaries, not hourly, so a day keeps the lookup off the hot path without
#: pinning a stale value across an upgrade.
CACHE_TTL_SECONDS = 86_400

#: Output tokens to allow per input token. Extraction returns candidates drawn from
#: the source, so the answer scales with the input rather than with the model.
OUTPUT_TO_INPUT_RATIO = 0.5

#: Floor for the derived budget. Not a per-model figure — it is the smallest answer
#: the candidate schema can hold with a handful of concepts and their quotes in it.
MIN_OUTPUT_TOKENS = 4_096

#: Rough chars-per-token, used only to size a budget. Deliberately low so the
#: estimate errs toward asking for more room than needed: over-asking costs nothing
#: (billing is on tokens produced, not on the ceiling requested), while under-asking
#: truncates the JSON and burns every retry.
CHARS_PER_TOKEN = 3.0


@dataclass(frozen=True)
class ModelLimits:
    """The ceilings for one model, and where each came from.

    `max_output_tokens` of None means "let the provider decide" — the caller should
    omit the parameter entirely rather than invent a number. That is the correct
    answer for OpenAI, whose model metadata does not publish an output ceiling and
    whose API defaults to the model's own maximum when the field is absent.
    """

    model: str
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
    source: str = "unknown"


def cache_path(config_dir: Path) -> Path:
    return config_dir / CACHE_FILENAME


def _read_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        # A corrupt cache is a cache miss, never an error: the whole point of this
        # file is to make discovery cheaper, so it must never make it fail.
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        # Losing the cache costs one extra request next run. Failing the extraction
        # over it would be a much worse trade.
        pass


def cached(config_dir: Path, provider: str, model: str,
           *, now: float | None = None,
           ttl: int = CACHE_TTL_SECONDS) -> ModelLimits | None:
    """A previously discovered limit, if it is still fresh."""
    entry = _read_cache(cache_path(config_dir)).get(f"{provider}:{model}")
    if not isinstance(entry, dict):
        return None
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return None
    if (now if now is not None else time.time()) - fetched_at > ttl:
        return None
    out = entry.get("max_output_tokens")
    inp = entry.get("max_input_tokens")
    return ModelLimits(
        model=model,
        max_output_tokens=out if isinstance(out, int) else None,
        max_input_tokens=inp if isinstance(inp, int) else None,
        source="cache",
    )


def remember(config_dir: Path, provider: str, limits: ModelLimits,
             *, now: float | None = None) -> None:
    path = cache_path(config_dir)
    data = _read_cache(path)
    data[f"{provider}:{limits.model}"] = {
        "max_output_tokens": limits.max_output_tokens,
        "max_input_tokens": limits.max_input_tokens,
        "fetched_at": now if now is not None else time.time(),
    }
    _write_cache(path, data)


def discover(client: Any, model: str) -> ModelLimits | None:
    """Ask the provider what this model accepts.

    Returns None when the provider does not publish the ceilings, or cannot be
    reached — both are ordinary outcomes here, handled by the caller falling through
    to a derived budget.
    """
    retrieve = getattr(getattr(client, "models", None), "retrieve", None)
    if retrieve is None:
        return None
    try:
        info = retrieve(model)
    except Exception:
        return None

    out = getattr(info, "max_tokens", None)
    inp = getattr(info, "max_input_tokens", None)
    if not isinstance(out, int) and not isinstance(inp, int):
        return None  # a model object with no ceilings tells us nothing
    return ModelLimits(
        model=model,
        max_output_tokens=out if isinstance(out, int) else None,
        max_input_tokens=inp if isinstance(inp, int) else None,
        source="provider",
    )


def derive_output_budget(system: str, user: str, *, ceiling: int | None = None) -> int:
    """An output budget sized from the prompt, clamped to `ceiling` when known.

    Used when the provider cannot tell us its own limit. Scaling with the input is
    what keeps this correct across models: a 200-word note and a two-hour transcript
    get different budgets from the same code, and neither is a guess about which
    model is serving the request.
    """
    prompt_tokens = (len(system) + len(user)) / CHARS_PER_TOKEN
    budget = max(int(prompt_tokens * OUTPUT_TO_INPUT_RATIO), MIN_OUTPUT_TOKENS)
    return min(budget, ceiling) if ceiling else budget


def resolve(provider: str, model: str, *, config_dir: Path,
            client: Any | None = None, configured: int | None = None,
            ttl: int = CACHE_TTL_SECONDS) -> ModelLimits:
    """The limits to use for one request. See the module docstring for the order."""
    if configured:
        return ModelLimits(model=model, max_output_tokens=configured, source="config")

    hit = cached(config_dir, provider, model, ttl=ttl)
    if hit is not None:
        return hit

    if client is not None:
        found = discover(client, model)
        if found is not None:
            remember(config_dir, provider, found)
            return found

    return ModelLimits(model=model, source="unknown")
