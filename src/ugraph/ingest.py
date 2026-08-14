"""
ingest.py — M0 ingestion spine: content-addressed, checkpointed, testable.

Design rule: the three re-ingest tests are the product. Everything here exists to
make them pass:
  1. ingesting the same document twice produces zero duplicates
  2. ingesting a modified document updates only affected chunks
  3. killing ingestion mid-document and rerunning completes cleanly

Layout:
    <kb>/raw/<slug>.md                 # immutable capture (markdown)
    <kb>/sources/<slug>.md             # provenance stub (ledger / lint)
    <kb>/.ugraph/chunks/<slug>/<chunk_id>.md
    <kb>/.ugraph/state/ingest-<slug>.json

Library-first: the CLI calls ingest_document() / capture_text(); nothing here prints.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ugraph import runs
from ugraph.config import Config
from ugraph.store import State, iso, read_md, slugify, write_md

JOB = "ingest"
CHUNK_SUFFIX = ".md"


@dataclass
class IngestResult:
    slug: str
    total_chunks: int
    written: int
    skipped: int
    removed: int
    resumed: bool
    raw_path: Path
    chunks_dir: Path


class IngestError(RuntimeError):
    pass


def _state_dir(cfg: Config) -> Path:
    return cfg.state / JOB


def _chunks_dir(cfg: Config, slug: str) -> Path:
    return cfg.kb / ".ugraph" / "chunks" / slug


def _raw_path(cfg: Config, slug: str) -> Path:
    return cfg.raw_dir / f"{slug}.md"


def content_id(text: str, doc_slug: str) -> str:
    """Stable chunk identity. Document slug namespaces identical prose so a
    copy-paste of the same note under a new title is a new document, not a
    collision."""
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    h.update("|".encode("utf-8"))
    h.update(doc_slug.encode("utf-8"))
    return h.hexdigest()[:16]


_HEADING = re.compile(r"^#{1,6}\s")


def chunk_text(text: str) -> list[str]:
    """Paragraph-ish chunks: blank lines are boundaries; consecutive headings
    attach to the following paragraph so citations stay on readable units.

    Deliberately naive for M0 (see docs/techniques/m0-chunking.md). If retrieval
    suffers on long answers at M3–M4, the scan says when to switch.
    """
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    chunks: list[str] = []
    current: list[str] = []
    pending_heading: str | None = None

    def flush() -> None:
        nonlocal pending_heading
        block = "\n".join(current).strip()
        if block:
            if pending_heading:
                block = pending_heading + "\n" + block
                pending_heading = None
            chunks.append(block)
        current.clear()

    for line in text.split("\n"):
        if not line.strip():
            flush()
            continue
        if _HEADING.match(line):
            flush()
            pending_heading = line.strip()
            continue
        current.append(line)
    flush()
    if pending_heading:
        chunks.append(pending_heading)
    return chunks


def _read_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt", ""}:
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        raise IngestError(
            "PDF ingest is M0-lite: convert to text first (pdftotext) and pass the "
            ".txt file. Layout/OCR PDF parsing is out of the 6-month scope."
        )
    raise IngestError(f"unsupported source type: {path.name}")


def _write_raw(cfg: Config, slug: str, text: str, meta: dict[str, Any]) -> Path:
    raw_path = _raw_path(cfg, slug)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    write_md(raw_path, text, meta)
    return raw_path


def _write_source_stub(
    cfg: Config,
    slug: str,
    *,
    title: str,
    source_uri: str,
    source_type: str,
) -> Path:
    """Pair every raw capture with a sources/ page so lint + ledger stay honest.

    Re-ingest must not clobber a finished summary the same way YouTube stubs
    preserve `summary_status: done`.
    """
    path = cfg.sources / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        existing, _ = read_md(path)

    today = iso()
    summarized = existing.get("summary_status") == "done"
    description = (
        existing.get("description")
        if summarized
        else "Not yet summarized — run extract to draft concepts from this capture."
    )
    raw_rel = f"../raw/{slug}.md"
    body = [
        f"# {title}",
        "",
        f"**{source_type}** · `{source_uri}`",
        "",
    ]
    if not summarized:
        body += [
            "> **Stub.** Capture is on disk; concept extraction has not run yet.",
            f"> Full text: [raw]({raw_rel})",
            "",
        ]
    else:
        body += [f"See [raw]({raw_rel}).", ""]

    write_md(
        path,
        "\n".join(body),
        {
            "type": "source",
            "source_type": source_type,
            "title": title,
            "description": description,
            "slug": slug,
            "url": source_uri if source_uri.startswith("http") else "",
            "raw": raw_rel,
            "summary_status": existing.get("summary_status", "pending"),
            "created": existing.get("created") or today,
            "updated": today,
        },
    )
    return path


def _state(cfg: Config, slug: str) -> State:
    return State(_state_dir(cfg), f"{JOB}-{slug}")


def ingest_document(
    cfg: Config,
    text: str,
    *,
    slug: str | None = None,
    title: str | None = None,
    source_uri: str = "stdin",
    source_type: str = "copy-paste",
    simulate_crash_after: int | None = None,
) -> IngestResult:
    """Ingest one text document into raw + chunks, resumably.

    simulate_crash_after exists ONLY for the kill-resume test: abort after N chunks
    so the caller can rerun and assert completion.
    """
    slug = slugify(slug or title or "capture")
    with runs.Run(cfg, "ingest", slug, source_type=source_type) as run:
        display_title = title or slug
        raw_path = _write_raw(
            cfg,
            slug,
            text,
            {
                "type": "raw-transcript",
                "immutable": True,
                "slug": slug,
                "title": display_title,
                "source_uri": source_uri,
                "source_type": source_type,
                "captured": iso(),
            },
        )
        source_path = _write_source_stub(
            cfg,
            slug,
            title=display_title,
            source_uri=source_uri,
            source_type=source_type,
        )
        run.stage("raw", path=str(raw_path), source=str(source_path))

        chunks = chunk_text(text)
        state = _state(cfg, slug)
        done: list[str] = state.get("done_ids", [])
        done_set = set(done)
        resumed = bool(done)

        chunks_dir = _chunks_dir(cfg, slug)
        chunks_dir.mkdir(parents=True, exist_ok=True)

        ids: list[str] = []
        written = 0
        skipped = 0

        for idx, chunk in enumerate(chunks):
            cid = content_id(chunk, slug)
            ids.append(cid)
            target = chunks_dir / f"{cid}{CHUNK_SUFFIX}"
            if cid in done_set and target.exists():
                skipped += 1
                continue
            write_md(
                target,
                chunk,
                {
                    "type": "chunk",
                    "doc": slug,
                    "chunk_id": cid,
                    "ordinal": idx,
                },
            )
            done.append(cid)
            done_set.add(cid)
            state.set("done_ids", done)
            state.checkpoint()
            written += 1
            if simulate_crash_after is not None and written >= simulate_crash_after:
                raise IngestError(f"simulated crash after {written} chunk(s)")

        # A modified document may drop chunks: remove files whose IDs are no longer
        # present so chunk count stays exactly == current document.
        existing = {p.stem for p in chunks_dir.glob(f"*{CHUNK_SUFFIX}")}
        wanted = set(ids)
        removed = 0
        for stale in existing - wanted:
            (chunks_dir / f"{stale}{CHUNK_SUFFIX}").unlink()
            removed += 1

        state.set("total_chunks", len(chunks))
        state.set("completed", True)
        state.checkpoint()

        run.stage("chunks", items_done=len(done), items_total=len(chunks),
                  written=written, skipped=skipped, removed=removed, resumed=resumed)

        return IngestResult(
            slug=slug,
            total_chunks=len(chunks),
            written=written,
            skipped=skipped,
            removed=removed,
            resumed=resumed,
            raw_path=raw_path,
            chunks_dir=chunks_dir,
        )


def ingest_path(cfg: Config, path: str | Path, **kwargs: Any) -> IngestResult:
    p = Path(path).expanduser()
    text = _read_source(p)
    kwargs.setdefault("title", p.stem)
    kwargs.setdefault("slug", p.stem)
    kwargs.setdefault("source_uri", str(p))
    kwargs.setdefault("source_type", "file")
    return ingest_document(cfg, text, **kwargs)


def capture_text(cfg: Config, text: str, **kwargs: Any) -> IngestResult:
    """Copy-paste entry point (stdin/clipboard)."""
    return ingest_document(cfg, text, **kwargs)


def derive_title(text: str) -> str:
    """Best-effort title for a paste with no explicit --title: first markdown
    heading, else the first words of the first non-empty line."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or "capture"
        return " ".join(stripped.split()[:8])
    return "capture"


def unique_slug(cfg: Config, base: str) -> str:
    """Collision-safe slug for captures. Explicit slugs never go through here —
    re-ingesting the same slug is the idempotency contract. Auto-named captures
    must not clobber yesterday's note."""
    slug = slugify(base)
    if not (cfg.raw_dir / f"{slug}.md").exists():
        return slug
    stamp = datetime.now().strftime("%H%M")
    candidate = f"{slug}-{stamp}"
    n = 2
    while (cfg.raw_dir / f"{candidate}.md").exists():
        candidate = f"{slug}-{stamp}-{n}"
        n += 1
    return candidate


def chunk_count(cfg: Config, slug: str) -> int:
    return len(list(_chunks_dir(cfg, slug).glob(f"*{CHUNK_SUFFIX}")))


def chunks(cfg: Config, slug: str) -> Iterable[Path]:
    yield from sorted(_chunks_dir(cfg, slug).glob(f"*{CHUNK_SUFFIX}"))
