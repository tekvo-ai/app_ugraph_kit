from ugraph.ingest import derive_title, unique_slug, ingest_document


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
