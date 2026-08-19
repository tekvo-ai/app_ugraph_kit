"""
embed.py — local embeddings with paper §3.2 chunk-hash reuse.

Derived state only: markdown chunks remain the source of truth. Vectors live under
`.ugraph/vectors/` and can be wiped / rebuilt without touching the KB.

The mechanism we take from omni-macos (Xiao, 2026, §3.2): on re-index, hash each
chunk together with the parameters that define what it means; if the hash matches
a stored row, skip the encoder forward pass and keep the vector. That is the
dominant ongoing cost once a corpus exists — not the first pass.

Hash key covers text + dim + chunking scheme. Encoder identity is held in the
store header: a model change forces a full re-index (same rule as the paper).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ugraph import ingest
from ugraph.config import Config
from ugraph.store import read_md

VECTORS_DIRNAME = "vectors"
CHUNKING_SCHEME = "paragraph-v1"
DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"


class EmbedError(RuntimeError):
    pass


class Encoder(Protocol):
    model: str
    dim: int

    def embed_one(self, text: str) -> list[float]: ...


@dataclass
class OllamaEncoder:
    """Mac-local encoder via Ollama HTTP. Default: nomic-embed-text (768d)."""

    model: str = DEFAULT_MODEL
    host: str = DEFAULT_OLLAMA
    dim: int = 0
    timeout: float = 120.0

    def embed_one(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host.rstrip('/')}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise EmbedError(
                f"cannot reach Ollama at {self.host}: {exc}\n"
                f"  Start it, then:  ollama pull {self.model}"
            ) from exc

        embeddings = data.get("embeddings")
        if not embeddings:
            # Older /api/embeddings shape.
            emb = data.get("embedding")
            if not emb:
                raise EmbedError(f"unexpected Ollama response keys: {list(data)}")
            vector = list(map(float, emb))
        else:
            vector = list(map(float, embeddings[0]))

        if self.dim and len(vector) != self.dim:
            raise EmbedError(
                f"model {self.model} returned dim {len(vector)}, expected {self.dim}"
            )
        if not self.dim:
            self.dim = len(vector)
        return vector


@dataclass
class FakeEncoder:
    """Deterministic, dependency-free encoder for tests and offline benches."""

    model: str = "fake-embed"
    dim: int = 32
    delay_s: float = 0.0
    calls: int = 0

    def embed_one(self, text: str) -> list[float]:
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [(digest[i % len(digest)] / 255.0) * 2 - 1 for i in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


def encode_hash(text: str, *, dim: int, chunking: str = CHUNKING_SCHEME) -> str:
    """Paper §3.2 key: text + parameters that determine what a chunk means.

    Encoder id is intentionally NOT in the key — changing models forces re-index
    via the store header instead.
    """
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    h.update(b"|")
    h.update(str(len(text)).encode("utf-8"))
    h.update(b"|")
    h.update(str(dim).encode("utf-8"))
    h.update(b"|")
    h.update(chunking.encode("utf-8"))
    return h.hexdigest()


@dataclass
class EmbedResult:
    slug: str
    total: int
    encoded: int
    reused: int
    removed: int
    seconds: float
    reuse: bool
    model: str
    dim: int


@dataclass
class BenchCase:
    name: str
    reuse_off_s: float
    reuse_on_s: float
    encoded_off: int
    encoded_on: int
    total: int

    @property
    def time_saved_pct(self) -> float:
        if self.reuse_off_s <= 0:
            return 0.0
        return (1.0 - self.reuse_on_s / self.reuse_off_s) * 100.0

    @property
    def encode_saved_pct(self) -> float:
        if self.encoded_off <= 0:
            return 0.0
        return (1.0 - self.encoded_on / self.encoded_off) * 100.0


@dataclass
class BenchReport:
    model: str
    dim: int
    cases: list[BenchCase] = field(default_factory=list)

    def as_table(self) -> str:
        lines = [
            f"model={self.model}  dim={self.dim}",
            "",
            f"{'edit':<12} {'reuse off':>12} {'reuse on':>12} "
            f"{'time saved':>11} {'enc off':>8} {'enc on':>8} {'enc saved':>10}",
            "-" * 78,
        ]
        for c in self.cases:
            lines.append(
                f"{c.name:<12} {c.reuse_off_s:10.3f}s {c.reuse_on_s:10.3f}s "
                f"{c.time_saved_pct:9.1f}% {c.encoded_off:8d} {c.encoded_on:8d} "
                f"{c.encode_saved_pct:9.1f}%"
            )
        return "\n".join(lines)


def _vectors_root(cfg: Config) -> Path:
    return cfg.kb / ".ugraph" / VECTORS_DIRNAME


def _store_path(cfg: Config, slug: str) -> Path:
    return _vectors_root(cfg) / f"{slug}.json"


def _load_store(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_store(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _chunk_records(cfg: Config, slug: str) -> list[tuple[str, int, str]]:
    """Return (chunk_id, ordinal, text) in ordinal order."""
    records: list[tuple[str, int, str]] = []
    for path in ingest.chunks(cfg, slug):
        meta, body = read_md(path)
        cid = str(meta.get("chunk_id") or path.stem)
        ordinal = int(meta.get("ordinal", len(records)))
        records.append((cid, ordinal, body.strip()))
    records.sort(key=lambda r: r[1])
    return records


def list_slugs(cfg: Config) -> list[str]:
    root = cfg.kb / ".ugraph" / "chunks"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def embed_document(
    cfg: Config,
    slug: str,
    *,
    encoder: Encoder,
    reuse: bool = True,
    modality: str = "text",
    on_encode: Callable[[str], None] | None = None,
) -> EmbedResult:
    """Embed one document's chunks. With reuse=True, skip unchanged hashes."""
    path = _store_path(cfg, slug)
    records = _chunk_records(cfg, slug)
    if not records:
        raise EmbedError(f"no chunks for {slug!r} — run ugraph ingest/capture first")

    prev = _load_store(path) if reuse else None
    dim = int(encoder.dim)

    # Model / dim mismatch → forced full re-index (paper §3.2).
    if prev is not None and (
        prev.get("model") != encoder.model
        or prev.get("chunking") != CHUNKING_SCHEME
        or (dim and int(prev.get("dim", 0)) != dim)
    ):
        prev = None

    # Prefer a known dim from the store so the first chunk can still reuse.
    if not dim and prev is not None:
        dim = int(prev.get("dim", 0))

    old_rows: dict[str, Any] = (prev or {}).get("rows", {})
    new_rows: dict[str, Any] = {}
    encoded = 0
    reused = 0
    t0 = time.perf_counter()

    for cid, ordinal, text in records:
        key = encode_hash(text, dim=dim) if dim else None
        hit = old_rows.get(cid) if (reuse and key) else None
        if (
            hit is not None
            and hit.get("hash") == key
            and isinstance(hit.get("vector"), list)
            and len(hit["vector"]) == dim
        ):
            new_rows[cid] = {
                "hash": key,
                "ordinal": ordinal,
                "modality": hit.get("modality", modality),
                "vector": hit["vector"],
            }
            reused += 1
            continue

        if on_encode:
            on_encode(cid)
        vector = encoder.embed_one(text)
        if not dim:
            dim = len(vector)
            encoder.dim = dim
        key = encode_hash(text, dim=dim)
        new_rows[cid] = {
            "hash": key,
            "ordinal": ordinal,
            "modality": modality,
            "vector": vector,
        }
        encoded += 1

    removed = len(set(old_rows) - set(new_rows))
    store = {
        "model": encoder.model,
        "dim": dim,
        "chunking": CHUNKING_SCHEME,
        "modality": modality,
        "rows": new_rows,
    }
    _save_store(path, store)
    return EmbedResult(
        slug=slug,
        total=len(records),
        encoded=encoded,
        reused=reused,
        removed=removed,
        seconds=time.perf_counter() - t0,
        reuse=reuse,
        model=encoder.model,
        dim=dim,
    )


def embed_all(
    cfg: Config,
    *,
    encoder: Encoder,
    reuse: bool = True,
    slugs: Iterable[str] | None = None,
) -> list[EmbedResult]:
    targets = list(slugs) if slugs is not None else list_slugs(cfg)
    if not targets:
        raise EmbedError("nothing to embed — ingest a document first")
    return [embed_document(cfg, slug, encoder=encoder, reuse=reuse) for slug in targets]


def _make_sections(n: int, *, prefix: str = "para") -> list[str]:
    """One heading+body unit per section — matches ingest.chunk_text boundaries."""
    parts: list[str] = []
    for i in range(n):
        # Long enough that a real local encoder does measurable work.
        filler = " ".join(f"{prefix}-{i}-token{j}" for j in range(40))
        parts.append(f"## Section {i}\n\n{filler}.")
    return parts


def _make_paragraphs(n: int, *, prefix: str = "para") -> str:
    return "\n\n".join(_make_sections(n, prefix=prefix))


def _index_from_base(
    cfg: Config,
    *,
    slug: str,
    base_text: str,
    edited_text: str,
    encoder: Encoder,
    reuse: bool,
) -> EmbedResult:
    """Index `base_text`, then re-index `edited_text` with reuse on or off.

    Mirrors the paper's edit path: the store holds vectors from the previous
    version of the same file; only chunks whose hash changed pay a forward pass.
    """
    ingest.ingest_document(
        cfg, base_text, slug=slug, title="Reuse bench", source_type="bench"
    )
    embed_document(cfg, slug, encoder=encoder, reuse=False)
    ingest.ingest_document(
        cfg, edited_text, slug=slug, title="Reuse bench", source_type="bench"
    )
    return embed_document(cfg, slug, encoder=encoder, reuse=reuse)


def run_reuse_bench(
    cfg: Config,
    *,
    encoder: Encoder,
    chunks: int = 16,
    slug: str = "reuse-bench",
) -> BenchReport:
    """Ablation matching paper Table 5: append and mid-file edit, reuse on vs off."""
    base = _make_paragraphs(chunks)
    # Probe dim / warm the model once before timed arms.
    ingest.ingest_document(
        cfg, base, slug=slug, title="Reuse bench", source_type="bench"
    )
    cold = embed_document(cfg, slug, encoder=encoder, reuse=False)
    report = BenchReport(model=encoder.model, dim=cold.dim)

    appended = base + "\n\n## Appendix\n\n" + " ".join(
        f"append-token{j}" for j in range(40)
    ) + "."

    append_on = _index_from_base(
        cfg, slug=slug, base_text=base, edited_text=appended, encoder=encoder, reuse=True
    )
    append_off = _index_from_base(
        cfg, slug=slug, base_text=base, edited_text=appended, encoder=encoder, reuse=False
    )
    report.cases.append(
        BenchCase(
            name="append",
            reuse_off_s=append_off.seconds,
            reuse_on_s=append_on.seconds,
            encoded_off=append_off.encoded,
            encoded_on=append_on.encoded,
            total=append_on.total,
        )
    )

    # Mid-file insert: with paragraph chunks, every untouched section keeps its
    # hash — stronger reuse than the paper's fixed character grid (~50% on insert).
    sections = _make_sections(chunks)
    mid = max(1, len(sections) // 2)
    new_sec = "## Inserted\n\n" + " ".join(f"insert-token{j}" for j in range(40)) + "."
    inserted = "\n\n".join(sections[:mid] + [new_sec] + sections[mid:])
    mid_on = _index_from_base(
        cfg, slug=slug, base_text=base, edited_text=inserted, encoder=encoder, reuse=True
    )
    mid_off = _index_from_base(
        cfg, slug=slug, base_text=base, edited_text=inserted, encoder=encoder, reuse=False
    )
    report.cases.append(
        BenchCase(
            name="mid-file",
            reuse_off_s=mid_off.seconds,
            reuse_on_s=mid_on.seconds,
            encoded_off=mid_off.encoded,
            encoded_on=mid_on.encoded,
            total=mid_on.total,
        )
    )
    return report


def resolve_encoder(
    *,
    model: str | None = None,
    host: str | None = None,
    fake: bool = False,
    fake_delay_ms: float = 0.0,
) -> Encoder:
    if fake:
        return FakeEncoder(delay_s=max(0.0, fake_delay_ms) / 1000.0)
    return OllamaEncoder(model=model or DEFAULT_MODEL, host=host or DEFAULT_OLLAMA)
