from ugraph.ingest import derive_title, unique_slug, ingest_document
from ugraph.store import read_md


def test_derive_title_prefers_heading():
    assert derive_title("\n\n# Retrieval notes\nbody") == "Retrieval notes"


def test_derive_title_falls_back_to_first_words():
    text = "some long paragraph about hybrid retrieval and reranking systems today"
    assert derive_title(text) == "some long paragraph about hybrid retrieval and reranking"


def test_derive_title_empty_is_capture():
    assert derive_title("   \n\n") == "capture"


def test_unique_slug_fresh(cfg):
    assert unique_slug(cfg, "My Note") == "my-note"


def test_unique_slug_avoids_clobber(cfg):
    ingest_document(cfg, "first version", slug="my-note", title="My Note")
    again = unique_slug(cfg, "My Note")
    assert again != "my-note"
    assert again.startswith("my-note-")


def test_capture_writes_immutable_raw_and_source_stub(cfg):
    result = ingest_document(
        cfg, "Hybrid retrieval combines lexical and semantic search.",
        slug="hybrid-note", title="Hybrid note",
    )
    raw_meta, _ = read_md(result.raw_path)
    assert raw_meta.get("immutable") is True
    assert raw_meta.get("type") == "raw-transcript"

    source = cfg.sources / "hybrid-note.md"
    assert source.is_file()
    src_meta, src_body = read_md(source)
    assert src_meta.get("type") == "source"
    assert src_meta.get("source_type") == "copy-paste"
    assert src_meta.get("raw") == "../raw/hybrid-note.md"
    assert "raw/hybrid-note.md" in src_body or "../raw/hybrid-note.md" in src_body

    # Re-ingest preserves a finished summary.
    write = source.read_text(encoding="utf-8")
    source.write_text(
        write.replace("summary_status: pending", "summary_status: done")
        .replace(
            "Not yet summarized — run extract to draft concepts from this capture.",
            "Hybrid retrieval is production-grade when lexical and dense agree.",
        ),
        encoding="utf-8",
    )
    ingest_document(
        cfg, "Hybrid retrieval combines lexical and semantic search.",
        slug="hybrid-note", title="Hybrid note",
    )
    again_meta, _ = read_md(source)
    assert again_meta.get("summary_status") == "done"
    assert "production-grade" in str(again_meta.get("description", ""))
