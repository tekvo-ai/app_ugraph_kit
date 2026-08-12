"""
promote.py — turn gated Phase A candidates into draft concept pages.

Phase B merge (many talks → one canonical page) still needs judgment. This module
does the mechanical half the tool can own safely:

  - write one draft concept page per gated candidate that does not already exist
  - cite the source with a verbatim quote + timestamp (or chunk anchor)
  - never overwrite a human/growing concept page

That keeps the pipeline end-to-end inside `ugraph` while preserving the
provenance contract: every claim still points at raw evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ugraph.config import Config
from ugraph.store import iso, read_md, slugify, write_md


@dataclass
class PromoteResult:
    candidates: int = 0
    written: int = 0
    skipped_existing: int = 0
    paths: list[Path] = field(default_factory=list)


def _source_rel(slug: str) -> str:
    """Candidate slugs look like `channel/video` → sources path from concepts/."""
    return f"../sources/{slug}.md"


def _citation_block(concept: dict, slug: str, title: str) -> str:
    quote = str(concept.get("verbatim_quote", "")).strip()
    stamp = str(concept.get("timestamp") or concept.get("anchor") or "").strip()
    rel = _source_rel(slug)
    short = title if len(title) <= 48 else title[:45] + "…"
    if stamp and ":" in stamp:
        cite = f"([{short}]({rel}) @ {stamp})"
    elif stamp:
        cite = f"([{short}]({rel}) · chunk `{stamp[:8]}`)"
    else:
        cite = f"([{short}]({rel}))"
    lines = [f"> {quote}", f"> {cite}", ""]
    return "\n".join(lines)


def promote_candidate_file(config: Config, path: Path) -> PromoteResult:
    """Promote one candidates/*.json into draft concept pages."""
    result = PromoteResult(candidates=1)
    data = json.loads(path.read_text(encoding="utf-8"))
    slug = str(data.get("slug") or path.stem)
    title = str(data.get("title") or slug)
    concepts = data.get("concepts") or []
    if not isinstance(concepts, list):
        return result

    for concept in concepts:
        name = str(concept.get("name") or "").strip()
        claim = str(concept.get("claim") or "").strip()
        if not name or not claim:
            continue
        concept_slug = slugify(name)
        out = config.concepts / f"{concept_slug}.md"
        if out.is_file():
            result.skipped_existing += 1
            continue

        domain = str(concept.get("domain") or "agentic_systems")
        body = [
            f"# {name[:1].upper() + name[1:]}",
            "",
            _citation_block(concept, slug, title),
            claim,
            "",
            "## Why it matters",
            "",
            "_Draft from Phase A — expand, merge, or reject before treating as canon._",
            "",
        ]
        write_md(out, "\n".join(body), {
            "type": "concept",
            "title": name[:1].upper() + name[1:] if name else concept_slug,
            "description": claim[:200],
            "domain": domain,
            "status": "draft",
            "tags": ["ugraph-promoted"],
            "sources": [slug],
            "created": iso(),
            "updated": iso(),
        })
        result.written += 1
        result.paths.append(out)
    return result


def promote_pending(config: Config, *, channel: str | None = None,
                    limit: int | None = None) -> PromoteResult:
    """Promote candidate JSON files that do not yet have draft concept pages.

    `channel` filters by candidate slug prefix (`channel/...`).
    """
    root = config.candidates
    aggregate = PromoteResult()
    if not root.is_dir():
        return aggregate

    files = sorted(root.glob("*.json"))
    if channel:
        prefix = channel.rstrip("/") + "/"
        files = [p for p in files
                 if _candidate_slug(p).startswith(prefix)
                 or _candidate_slug(p).startswith(channel + "/")]

    if limit is not None:
        files = files[:limit]

    for path in files:
        one = promote_candidate_file(config, path)
        aggregate.candidates += one.candidates
        aggregate.written += one.written
        aggregate.skipped_existing += one.skipped_existing
        aggregate.paths.extend(one.paths)
    return aggregate


def _candidate_slug(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("slug") or path.stem)
    except Exception:
        return path.stem


def mark_source_extracted(config: Config, slug: str) -> None:
    """Flip summary_status when concepts were promoted for a source."""
    # slug is channel/video
    path = config.sources / f"{slug}.md"
    if not path.is_file():
        return
    meta, body = read_md(path)
    if meta.get("summary_status") == "done":
        return
    meta["summary_status"] = "candidates"
    write_md(path, body, meta)
