from ugraph.ingest import chunk_text, content_id


def test_chunk_text_paragraphs():
    text = "# Title\n\nfirst para\n\nsecond para"
    chunks = chunk_text(text)
    assert chunks[0].startswith("# Title")
    assert "first para" in chunks[0]
    assert chunks[-1] == "second para"


def test_content_id_stable_and_namespaced():
    a = content_id("hello", "doc")
    assert a == content_id("hello", "doc")
    assert a != content_id("hello", "other-doc")
    assert a != content_id("hello!", "doc")
