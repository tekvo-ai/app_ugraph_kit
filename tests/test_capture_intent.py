"""Bare `ugraph` detect → preview before confirm."""

from ugraph.capture_intent import classify, format_preview


def test_classify_playlist():
    url = (
        "https://www.youtube.com/playlist?list=PLE9hy4A7ZTmpGq7GHf5tgGFWh2277AeDR"
    )
    intent = classify(url)
    assert intent.kind == "youtube_playlist"
    assert "playlist" in intent.label.lower()
    assert url in intent.detail_lines[0]
    preview = format_preview(intent)
    assert "Detected: YouTube playlist" in preview


def test_classify_watch_with_list_is_playlist():
    url = (
        "https://www.youtube.com/watch?v=GrNbuWWJYiI"
        "&list=PLE9hy4A7ZTmpGq7GHf5tgGFWh2277AeDR"
    )
    assert classify(url).kind == "youtube_playlist"


def test_classify_channel_feed():
    url = "https://www.youtube.com/@aiDotEngineer/videos"
    intent = classify(url)
    assert intent.kind == "youtube_feed"
    assert "feed" in intent.label.lower()


def test_classify_person_video():
    url = "https://www.youtube.com/watch?v=GrNbuWWJYiI"
    intent = classify(url)
    assert intent.kind == "youtube_person"
    assert "YouTube" in intent.label


def test_classify_text_shows_title_and_preview():
    text = "# Hybrid retrieval\n\nFirst paragraph here.\n\nSecond bit."
    intent = classify(text)
    assert intent.kind == "text"
    assert intent.label == "text capture"
    joined = "\n".join(intent.detail_lines)
    assert "Hybrid retrieval" in joined
    assert "First paragraph" in joined
    assert "characters" in joined


def test_format_preview_indents_details():
    intent = classify("hello world note about agents")
    out = format_preview(intent)
    assert out.startswith("Detected: text capture")
    assert "\n  title:" in out
