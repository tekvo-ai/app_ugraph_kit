"""
runs.py — one append-only event stream for every job, and the readers that render it.

The ledger answers "where is this item in its lifecycle". This answers a different
question: "what is happening *right now*, in which module, on which item, at which
step, for how long". Both live in the state dir; both are append-only JSONL, because
a stream you can `tail` beats a database you have to query.

The record doubles as the M1 eval run-record seed: module, slug, step, elapsed_ms,
backend, model, attempt, rejected — cost/token fields join when the provider layer
lands (M2), config_hash/code_sha when the eval harness does (M1). Emitting the spine
now means those milestones add fields, not plumbing.

Granularity is the slug, not the chunk. Per-chunk events would make the stream noisy
enough that nobody tails it.

    from ugraph import runs

    with runs.Run(cfg, "extract", slug, backend="ollama", model="qwen2.5:7b") as run:
        ... work ...
        run.stage("gate", attempt=2, rejected=1)
    # exiting the block emits done/fail with total elapsed
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ugraph.config import Config

RUNS_FILENAME = "runs.jsonl"


def _path(config: Config) -> Path:
    return Path(config.state) / RUNS_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def emit(config: Config, module: str, event: str, run: str | None = None,
         slug: str | None = None, **fields: Any) -> dict[str, Any]:
    """Append one event. Never raises: observability must not take down the job it
    observes. A corrupt state dir or full disk is reported by the job itself."""
    record = {
        "ts": _now(),
        "run": run or "-",
        "module": module,
        "event": event,
        **({"slug": slug} if slug else {}),
        **fields,
    }
    try:
        path = _path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass
    return record


class Run:
    """One job execution from start to done/fail, emitting as it goes."""

    def __init__(self, config: Config, module: str, slug: str | None = None, **meta: Any):
        self.config = config
        self.module = module
        self.slug = slug
        self.meta = {k: v for k, v in meta.items() if v}
        self.id = uuid.uuid4().hex[:8]
        self._start = time.monotonic()
        self._finished = False

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)

    def __enter__(self) -> "Run":
        # pid lets readers tell a live run from a killed one: a run whose process
        # is gone but that never emitted done/fail is stale, not active.
        emit(self.config, self.module, "start", run=self.id, slug=self.slug,
             pid=os.getpid(), **self.meta)
        return self

    def stage(self, step: str, **fields: Any) -> None:
        emit(self.config, self.module, "stage", run=self.id, slug=self.slug,
             step=step, elapsed_ms=self.elapsed_ms, **fields)

    def fail(self, error: str, **fields: Any) -> None:
        """Mark the run failed without raising — for error *returns*, where an
        exception never travels through __exit__."""
        if self._finished:
            return
        self._finished = True
        emit(self.config, self.module, "fail", run=self.id, slug=self.slug,
             elapsed_ms=self.elapsed_ms, error=error, **self.meta, **fields)

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if self._finished:
            return False
        if exc is None:
            emit(self.config, self.module, "done", run=self.id, slug=self.slug,
                 elapsed_ms=self.elapsed_ms, **self.meta)
        else:
            emit(self.config, self.module, "fail", run=self.id, slug=self.slug,
                 elapsed_ms=self.elapsed_ms, error=f"{type(exc).__name__}: {exc}",
                 **self.meta)
        return False  # never swallow the job's own exception


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def read(config: Config, limit: int | None = None) -> list[dict[str, Any]]:
    """All events, oldest first. A personal KB produces kilobytes of this a day;
    reading whole files stays honest far longer than cleverness here."""
    path = _path(config)
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn last line after a crash is expected, not fatal
    return events[-limit:] if limit else events


def for_slug(config: Config, slug: str, limit: int = 100) -> list[dict[str, Any]]:
    return [e for e in read(config) if e.get("slug") == slug][-limit:]


def _pid_alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError, OverflowError):
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def latest_per_run(config: Config, limit: int = 200) -> list[dict[str, Any]]:
    """Newest event for each run, ordered by most recent activity.

    A run with a start but no done/fail is *active* — its elapsed is computed
    against now so `ps` shows a live clock rather than the last stale checkpoint.
    Exception: if the run's process is dead, the job was killed mid-flight and
    the terminal event never happened — that row is *stale*, not active.
    """
    events = read(config, limit=limit)
    by_run: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        rid = event.get("run", "-")
        if rid not in by_run:
            order.append(rid)
            by_run[rid] = {"_first_ts": event["ts"]}
        by_run[rid].update({k: v for k, v in event.items() if v is not None})

    out = []
    for rid in reversed(order):
        latest = by_run[rid]
        active = latest.get("event") not in ("done", "fail")
        stale = bool(active and latest.get("pid") and not _pid_alive(latest["pid"]))
        row = {k: v for k, v in latest.items() if k != "_first_ts"}
        row["active"] = active and not stale
        row["stale"] = stale
        if row["active"]:
            try:
                started = datetime.fromisoformat(latest["_first_ts"])
                row["elapsed_ms"] = int(
                    (datetime.now(timezone.utc) - started).total_seconds() * 1000)
            except Exception:
                row.setdefault("elapsed_ms", 0)
        out.append(row)
    return out


def iter_active(config: Config) -> Iterable[dict[str, Any]]:
    return (r for r in latest_per_run(config) if r["active"])
