"""
capture_intent.py — classify clipboard/paste before bare `ugraph` acts.

The daily loop is detect → show → confirm → act. This module is the detect/show
half: no I/O beyond pure classification, so tests and the CLI share one path.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from ugraph import ingest
from ugraph import person as person_mod
from ugraph.sources import youtube as youtube_mod

Kind = str  # "youtube_playlist" | "youtube_feed" | "youtube_person" | "text"


@dataclass(frozen=True)
class CaptureIntent:
    kind: Kind
    text: str
    label: str
    confirm_prompt: str
    detail_lines: tuple[str, ...]


def _feed_kind(url: str) -> Kind:
    parsed = urlparse(url.strip())
    if parse_qs(parsed.query).get("list") or parsed.path.rstrip("/").endswith(
        "/playlist"
    ):
        return "youtube_playlist"
    return "youtube_feed"


def classify(text: str) -> CaptureIntent:
    """Decide what bare `ugraph` should do with pasted/clipboard content."""
    stripped = text.strip()
    if not stripped:
        return CaptureIntent(
            kind="text",
            text=text,
            label="empty",
            confirm_prompt="Ingest this into your knowledge base? [Y/n]",
            detail_lines=("(nothing)",),
        )

    if youtube_mod.is_feed_url(stripped):
        kind = _feed_kind(stripped)
        if kind == "youtube_playlist":
            label = "YouTube playlist"
            prompt = "Ingest this playlist into your knowledge base? [Y/n]"
        else:
            label = "YouTube channel feed"
            prompt = "Ingest this channel feed into your knowledge base? [Y/n]"
        return CaptureIntent(
            kind=kind,
            text=stripped,
            label=label,
            confirm_prompt=prompt,
            detail_lines=(f"url: {stripped}",),
        )

    if person_mod.is_supported_url(stripped):
        return CaptureIntent(
            kind="youtube_person",
            text=stripped,
            label="YouTube link (person / video / channel)",
            confirm_prompt="Resolve and add this to your knowledge base? [Y/n]",
            detail_lines=(f"url: {stripped}",),
        )

    title = ingest.derive_title(stripped)
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    chars = len(stripped)

    def _clip(line: str, width: int = 88) -> str:
        line = line.replace("\t", " ")
        return line if len(line) <= width else line[: width - 1] + "…"

    preview = [_clip(ln) for ln in lines[:4]]
    if len(lines) > 4:
        preview.append(f"… (+{len(lines) - 4} more lines)")
    detail = (
        f"title: {title}",
        f"size:  {chars:,} characters, {len(lines)} line(s)",
        "---",
        *preview,
    )
    return CaptureIntent(
        kind="text",
        text=text,
        label="text capture",
        confirm_prompt="Ingest this into your knowledge base? [Y/n]",
        detail_lines=tuple(detail),
    )


def format_preview(intent: CaptureIntent) -> str:
    """Human-readable block printed before the confirm prompt."""
    lines = [f"Detected: {intent.label}", *[f"  {line}" for line in intent.detail_lines]]
    return "\n".join(lines)
