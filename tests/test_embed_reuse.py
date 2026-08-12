"""Paper §3.2 chunk-hash reuse: unchanged chunks skip the encoder."""

from pathlib import Path

from ugraph import config as config_mod
from ugraph import embed, ingest


def _cfg(tmp_path: Path) -> config_mod.Config:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "raw").mkdir()
    (kb / ".ugraph" / "chunks").mkdir(parents=True)
    return config_mod.Config(kb=kb)


def test_encode_hash_stable_and_param_sensitive():
    a = embed.encode_hash("hello", dim=768)
    assert a == embed.encode_hash("hello", dim=768)
    assert a != embed.encode_hash("hello!", dim=768)
    assert a != embed.encode_hash("hello", dim=1024)


def test_reuse_skips_unchanged_chunks(tmp_path: Path):
    cfg = _cfg(tmp_path)
    text = "## A\n\none\n\n## B\n\ntwo\n\n## C\n\nthree"
    ingest.ingest_document(cfg, text, slug="doc", title="Doc")
    enc = embed.FakeEncoder(delay_s=0)

    first = embed.embed_document(cfg, "doc", encoder=enc, reuse=True)
    assert first.encoded == 3
    assert first.reused == 0
    assert enc.calls == 3

    # Identical re-index: every forward pass skipped.
    enc.calls = 0
    second = embed.embed_document(cfg, "doc", encoder=enc, reuse=True)
    assert second.encoded == 0
    assert second.reused == 3
    assert enc.calls == 0


def test_append_reuses_prefix(tmp_path: Path):
    cfg = _cfg(tmp_path)
    base = "## A\n\none\n\n## B\n\ntwo\n\n## C\n\nthree"
    ingest.ingest_document(cfg, base, slug="doc", title="Doc")
    enc = embed.FakeEncoder()
    embed.embed_document(cfg, "doc", encoder=enc, reuse=False)

    appended = base + "\n\n## D\n\nfour"
    ingest.ingest_document(cfg, appended, slug="doc", title="Doc")
    enc.calls = 0
    result = embed.embed_document(cfg, "doc", encoder=enc, reuse=True)
    assert result.total == 4
    assert result.encoded == 1
    assert result.reused == 3
    assert enc.calls == 1


def test_no_reuse_reencodes_everything(tmp_path: Path):
    cfg = _cfg(tmp_path)
    text = "## A\n\none\n\n## B\n\ntwo"
    ingest.ingest_document(cfg, text, slug="doc", title="Doc")
    enc = embed.FakeEncoder()
    embed.embed_document(cfg, "doc", encoder=enc, reuse=False)
    enc.calls = 0
    result = embed.embed_document(cfg, "doc", encoder=enc, reuse=False)
    assert result.encoded == 2
    assert result.reused == 0
    assert enc.calls == 2


def test_model_change_forces_reindex(tmp_path: Path):
    cfg = _cfg(tmp_path)
    text = "## A\n\none\n\n## B\n\ntwo"
    ingest.ingest_document(cfg, text, slug="doc", title="Doc")
    a = embed.FakeEncoder(model="fake-a", dim=32)
    embed.embed_document(cfg, "doc", encoder=a, reuse=True)
    b = embed.FakeEncoder(model="fake-b", dim=32)
    result = embed.embed_document(cfg, "doc", encoder=b, reuse=True)
    assert result.encoded == 2
    assert result.reused == 0


def test_bench_shows_savings(tmp_path: Path):
    cfg = _cfg(tmp_path)
    enc = embed.FakeEncoder(delay_s=0.002)
    report = embed.run_reuse_bench(cfg, encoder=enc, chunks=8, slug="bench")
    assert len(report.cases) == 2
    append = report.cases[0]
    assert append.name == "append"
    assert append.encoded_on < append.encoded_off
    assert append.encode_saved_pct > 50
    mid = report.cases[1]
    assert mid.encoded_on < mid.encoded_off
