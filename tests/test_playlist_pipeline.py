"""Playlist listing + draft concept promotion — feed pipeline building blocks."""

from __future__ import annotations

import json
from pathlib import Path

from ugraph import promote
from ugraph.config import Config
from ugraph.sources import youtube


def test_is_feed_url_playlist():
    url = "https://www.youtube.com/playlist?list=PLE9hy4A7ZTmpGq7GHf5tgGFWh2277AeDR"
    assert youtube.is_feed_url(url)
    assert youtube._listing_url(url) == url.rstrip("/")


def test_listing_url_channel_gets_videos_suffix():
    assert youtube._listing_url("https://www.youtube.com/@aiDotEngineer").endswith(
        "/videos"
    )


def test_listing_url_does_not_double_videos():
    url = "https://www.youtube.com/@aiDotEngineer/videos"
    assert youtube._listing_url(url) == url


def test_promote_writes_draft_concept(tmp_path: Path):
    kb = tmp_path / "kb"
    (kb / "concepts").mkdir(parents=True)
    cand = tmp_path / "candidates"
    cand.mkdir()
    payload = {
        "slug": "demo/talk",
        "title": "Demo Talk",
        "concepts": [
            {
                "name": "harness loop",
                "claim": "The harness owns the loop around the model.",
                "verbatim_quote": "the harness owns the loop",
                "timestamp": "00:01:02",
                "domain": "agentic_systems",
            }
        ],
    }
    path = cand / "demo-talk.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    cfg = Config(kb=kb, raw={"candidates": str(cand)})
    result = promote.promote_candidate_file(cfg, path)
    assert result.written == 1
    out = kb / "concepts" / "harness-loop.md"
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "status: draft" in text
    assert "the harness owns the loop" in text
    assert "../sources/demo/talk.md" in text

    # Second promote is idempotent — never clobber.
    again = promote.promote_candidate_file(cfg, path)
    assert again.written == 0
    assert again.skipped_existing == 1
