"""Resume / checkpoint hardening: repair-state, billing abort, status alignment."""

from __future__ import annotations

import json
from pathlib import Path

from ugraph import extract, status
from ugraph.config import Config
from ugraph.sources import youtube
from ugraph.store import State, write_md


def _cfg(tmp_path: Path) -> Config:
    kb = tmp_path / "kb"
    for sub in ("raw", "sources", "concepts"):
        (kb / sub).mkdir(parents=True)
    state = tmp_path / ".ugraph" / "state"
    state.mkdir(parents=True)
    cand = tmp_path / ".ugraph" / "candidates"
    cand.mkdir(parents=True)
    return Config(
        kb=kb,
        state_dir=state,
        raw={"candidates": str(cand)},
    )


def test_channel_state_key_canonicalizes_playlist():
    watch = (
        "https://www.youtube.com/watch?v=GrNbuWWJYiI"
        "&list=PLE9hy4A7ZTmpGq7GHf5tgGFWh2277AeDR"
    )
    playlist = (
        "https://www.youtube.com/playlist?list=PLE9hy4A7ZTmpGq7GHf5tgGFWh2277AeDR"
    )
    assert youtube.channel_state_key(watch) == playlist
    assert youtube.channel_state_key(playlist) == playlist


def test_repair_state_drops_missing_and_merges_aliases(tmp_path: Path):
    cfg = _cfg(tmp_path)
    channel = "demo-ch"
    raw_dir = cfg.raw_dir / channel
    raw_dir.mkdir(parents=True)
    write_md(
        raw_dir / "kept.md",
        "hello",
        {"type": "raw-transcript", "youtube_id": "KEEP1", "slug": f"{channel}/kept"},
    )
    # Pollution: same ID exists under another channel — must NOT count for repair.
    other = cfg.raw_dir / "other-ch"
    other.mkdir(parents=True)
    write_md(
        other / "polluted.md",
        "nope",
        {"type": "raw-transcript", "youtube_id": "GONE1", "slug": "other-ch/polluted"},
    )

    playlist = "https://www.youtube.com/playlist?list=PLtestRepair"
    alias = "https://www.youtube.com/watch?v=x&list=PLtestRepair"
    state = State(cfg.state, youtube.JOB)
    state.set(
        "channels",
        {
            playlist: {
                "slug": channel,
                "ingested": ["KEEP1", "GONE1", "GONE2"],
                "failed": {},
            },
            alias: {
                "slug": "alias-slug",
                "ingested": ["GONE3"],
                "failed": {"FAIL1": {"reason": "no captions", "attempts": 1}},
            },
        },
    )
    state.checkpoint()

    result = youtube.repair_state(cfg, alias, slug=channel)
    assert result["removed"] == 3  # GONE1 (other folder), GONE2, GONE3
    assert result["kept"] == 1
    assert len(result["merged_aliases"]) == 1

    channels = State(cfg.state, youtube.JOB).get("channels", {})
    assert alias not in channels
    assert set(channels[playlist]["ingested"]) == {"KEEP1"}
    assert "FAIL1" in channels[playlist]["failed"]


def test_hard_provider_failure_detects_credits():
    assert extract.is_hard_provider_failure(
        "BadRequestError: Your credit balance is too low to access the Anthropic API"
    )
    assert not extract.is_hard_provider_failure("response was not JSON")


def test_extract_run_aborts_on_hard_failure(tmp_path: Path):
    cfg = _cfg(tmp_path)
    ch = cfg.sources / "ch"
    ch.mkdir(parents=True)
    raw = cfg.raw_dir / "ch"
    raw.mkdir(parents=True)
    for i, name in enumerate(["a-talk", "b-talk", "c-talk"]):
        write_md(
            raw / f"{name}.md",
            f"body {name}",
            {"type": "raw-transcript", "slug": f"ch/{name}"},
        )
        write_md(
            ch / f"{name}.md",
            f"# {name}",
            {
                "type": "source",
                "slug": f"ch/{name}",
                "title": name,
                "raw": f"../../raw/ch/{name}.md",
                "summary_status": "pending",
                "published": f"2026-01-0{i+1}",
            },
        )

    calls = {"n": 0}

    class BoomBackend:
        name = "api"

        def complete(self, system: str, user: str) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError(
                    "BadRequestError: Your credit balance is too low to access "
                    "the Anthropic API"
                )
            return json.dumps({"concepts": [], "yield": "none"})

    result = extract.run(cfg, BoomBackend(), limit=3, channel="ch")
    assert result["aborted"] is True
    assert result["attempted"] == 1
    assert calls["n"] == 1
    assert "ugraph extract" in result["resume"]


def test_status_counts_candidate_as_extracted(tmp_path: Path):
    cfg = _cfg(tmp_path)
    ch = cfg.sources / "ch"
    ch.mkdir(parents=True)
    raw = cfg.raw_dir / "ch"
    raw.mkdir(parents=True)
    write_md(
        raw / "talk.md",
        "transcript",
        {"type": "raw-transcript", "slug": "ch/talk"},
    )
    write_md(
        ch / "talk.md",
        "# talk",
        {
            "type": "source",
            "slug": "ch/talk",
            "title": "talk",
            "raw": "../../raw/ch/talk.md",
            "summary_status": "pending",
        },
    )
    (cfg.candidates / "talk.json").write_text(
        json.dumps({"slug": "ch/talk", "concepts": []}), encoding="utf-8"
    )

    stats = status.collect(cfg, channel="ch")
    assert stats["extracted"] == 1
    assert stats["pending_total"] == 0
    assert stats["candidates"] == 1
