"""verify.py is the module the README's central claim rests on.

The two passes are deliberately asymmetric, and that asymmetry is the thing worth
pinning: candidates are machine output and checked strictly; pages are human prose and
checked timidly, because a checker that cries wolf gets muted. Tests here assert both
what it catches *and* what it declines to accuse.
"""

from __future__ import annotations

import json

from conftest import concept, source

from ugraph import verify

TRANSCRIPT = """[00:00:00] Welcome to the talk about retrieval systems.

[00:01:00] Hybrid retrieval combines lexical and semantic search.

[00:02:00] Chunking splits a document into retrievable units for indexing.

[00:03:00] Evaluation is the only way to know whether any of this helped.
"""


def transcript(config, slug="talk", text=TRANSCRIPT):
    """A raw transcript with real [HH:MM:SS] caption markers."""
    from ugraph.store import write_md
    return write_md(config.kb / "raw" / f"{slug}.md", text,
                    {"type": "raw-transcript", "immutable": True, "slug": slug})


def candidate(config, slug="talk", concepts=None):
    config.candidates.mkdir(parents=True, exist_ok=True)
    payload = {"slug": slug, "concepts": concepts or []}
    path = config.candidates / f"{slug}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def kinds(issues) -> list[str]:
    return [i.kind for i in issues]


# ---------------------------------------------------------------------------
# verify_candidates — machine output, checked strictly
# ---------------------------------------------------------------------------

def test_no_candidates_directory_is_not_an_issue(populated):
    assert verify.verify_candidates(populated) == []


def test_a_verbatim_quote_at_the_right_timestamp_passes(fresh):
    transcript(fresh)
    candidate(fresh, concepts=[{
        "title": "Hybrid retrieval",
        "verbatim_quote": "Hybrid retrieval combines lexical and semantic search.",
        "timestamp": "00:01:00",
    }])
    assert verify.verify_candidates(fresh) == []


def test_a_paraphrase_is_not_verbatim(fresh):
    transcript(fresh)
    candidate(fresh, concepts=[{
        "title": "Hybrid retrieval",
        # plausible, fluent, and not what the speaker said
        "verbatim_quote": "Hybrid retrieval blends keyword and vector search.",
        "timestamp": "00:01:00",
    }])
    assert kinds(verify.verify_candidates(fresh)) == ["not-verbatim"]


def test_a_quote_from_the_neighbouring_paragraph_is_a_timestamp_mismatch(fresh):
    transcript(fresh)
    candidate(fresh, concepts=[{
        "title": "Chunking",
        # real text, but it lives at 00:02:00, not 00:01:00
        "verbatim_quote": "Chunking splits a document into retrievable units",
        "timestamp": "00:01:00",
    }])
    assert kinds(verify.verify_candidates(fresh)) == ["timestamp-mismatch"]


def test_a_timestamp_past_the_end_of_the_transcript_is_missing(fresh):
    transcript(fresh)
    candidate(fresh, concepts=[{
        "title": "Hybrid retrieval",
        "verbatim_quote": "Hybrid retrieval combines lexical and semantic search.",
        "timestamp": "09:59:59",
    }])
    assert kinds(verify.verify_candidates(fresh)) == ["timestamp-missing"]


def test_candidates_with_no_transcript_report_once_not_per_quote(fresh):
    candidate(fresh, concepts=[
        {"title": "A", "verbatim_quote": "something said", "timestamp": "00:01:00"},
        {"title": "B", "verbatim_quote": "something else said", "timestamp": "00:02:00"},
    ])
    issues = verify.verify_candidates(fresh)
    assert kinds(issues) == ["no-transcript"]
    assert "2 quote(s) unverifiable" in issues[0].detail


def test_an_entry_with_no_quote_claims_nothing_and_is_skipped(fresh):
    transcript(fresh)
    candidate(fresh, concepts=[{"title": "Just a concept", "timestamp": "00:01:00"}])
    assert verify.verify_candidates(fresh) == []


def test_normalization_covers_whitespace_and_curly_quotes(fresh):
    transcript(fresh, text='[00:01:00] He said "hello there" to the room, at length.\n')
    candidate(fresh, concepts=[{
        "title": "Greeting",
        # curly quotes and a collapsed newline — representation, not wording
        "verbatim_quote": 'He said “hello there” to the\nroom, at length.',
        "timestamp": "00:01:00",
    }])
    assert verify.verify_candidates(fresh) == []


def test_normalization_never_forgives_a_changed_word(fresh):
    transcript(fresh)
    candidate(fresh, concepts=[{
        "title": "Hybrid retrieval",
        "verbatim_quote": "Hybrid retrieval combines lexical and SEMANTIC search!",
        "timestamp": "00:01:00",
    }])
    # case and trailing punctuation differ; the checker must not silently accept a
    # rewritten quote, so this is reported rather than normalized away
    assert kinds(verify.verify_candidates(fresh)) == ["not-verbatim"]


def test_unparseable_candidate_json_is_skipped_silently(fresh):
    transcript(fresh)
    fresh.candidates.mkdir(parents=True, exist_ok=True)
    (fresh.candidates / "broken.json").write_text("{not json", encoding="utf-8")
    assert verify.verify_candidates(fresh) == []


def test_candidate_without_a_concepts_list_is_skipped_silently(fresh):
    transcript(fresh)
    fresh.candidates.mkdir(parents=True, exist_ok=True)
    (fresh.candidates / "odd.json").write_text(
        json.dumps({"slug": "talk", "concepts": "not-a-list"}), encoding="utf-8")
    assert verify.verify_candidates(fresh) == []


def test_the_issue_names_the_file_source_and_quote(fresh):
    transcript(fresh)
    candidate(fresh, concepts=[{
        "title": "X", "verbatim_quote": "never said this at all, truly",
        "timestamp": "00:01:00"}])
    issue = verify.verify_candidates(fresh)[0]
    assert issue.file.endswith("talk.json")
    assert issue.source == "talk"
    assert "never said this" in issue.quote
    assert issue.detail


# ---------------------------------------------------------------------------
# verify_pages — human prose, checked timidly
# ---------------------------------------------------------------------------

def cited_source(config, slug="talk"):
    transcript(config, slug)
    source(config, slug, source_type="video", youtube_id="abc123",
           url=f"https://youtu.be/{slug}", published="2026-08-01", duration="10:00",
           raw=f"../raw/{slug}.md", body="A talk.\n")


def test_a_page_quoting_correctly_passes(fresh):
    cited_source(fresh)
    concept(fresh, "hybrid", body=(
        'The speaker put it plainly: "Hybrid retrieval combines lexical and '
        'semantic search." ([Talk](../sources/talk.md) @ 00:01:00)\n'))
    assert verify.verify_pages(fresh) == []


def test_a_page_misquoting_is_not_verbatim(fresh):
    cited_source(fresh)
    concept(fresh, "hybrid", body=(
        'The speaker said "Hybrid retrieval blends keyword and vector searching '
        'together." ([Talk](../sources/talk.md) @ 00:01:00)\n'))
    assert kinds(verify.verify_pages(fresh)) == ["not-verbatim"]


def test_an_elided_quote_is_checked_fragment_by_fragment(fresh):
    cited_source(fresh)
    concept(fresh, "elided", body=(
        'They noted that "Hybrid retrieval combines ... semantic search." '
        '([Talk](../sources/talk.md) @ 00:01:00)\n'))
    assert verify.verify_pages(fresh) == []


def test_a_blockquote_citation_is_checked(fresh):
    cited_source(fresh)
    concept(fresh, "quoted", body=(
        "> Hybrid retrieval combines lexical and semantic search.\n"
        "> ([Talk](../sources/talk.md) @ 00:01:00)\n"))
    assert verify.verify_pages(fresh) == []


def test_paraphrase_with_no_quote_marks_is_never_accused(fresh):
    cited_source(fresh)
    concept(fresh, "paraphrased", body=(
        "The talk argues that combining retrieval strategies helps, which is a "
        "restatement rather than a quotation. ([Talk](../sources/talk.md) @ 00:01:00)\n"))
    assert verify.verify_pages(fresh) == []


def test_a_short_scare_quote_is_never_accused(fresh):
    cited_source(fresh)
    concept(fresh, "term-of-art", body=(
        'They call it "jagged intelligence". ([Talk](../sources/talk.md) @ 00:01:00)\n'))
    assert verify.verify_pages(fresh) == []


def test_unbalanced_quote_marks_are_not_paired(fresh):
    cited_source(fresh)
    concept(fresh, "unbalanced", body=(
        'An opening " that never closes, said at length and with feeling here. '
        '([Talk](../sources/talk.md) @ 00:01:00)\n'))
    assert verify.verify_pages(fresh) == []


def test_a_bare_continuation_citation_is_skipped(fresh):
    cited_source(fresh)
    concept(fresh, "continued", body=(
        'First: "Hybrid retrieval combines lexical and semantic search." '
        '([Talk](../sources/talk.md) @ 00:01:00)\n\n'
        'Then: "Something entirely invented and never spoken aloud here." (@ 00:02:00)\n'))
    # the second citation names no source, so it asserts nothing this checker can test
    assert verify.verify_pages(fresh) == []


def test_timestamp_tolerance_forgives_a_hand_written_citation(fresh):
    cited_source(fresh)
    concept(fresh, "near-enough", body=(
        'As stated: "Hybrid retrieval combines lexical and semantic search." '
        '([Talk](../sources/talk.md) @ 00:01:30)\n'))
    # 30s away, inside PAGE_TIMESTAMP_TOLERANCE_S — a real quote must not be accused
    assert verify.verify_pages(fresh) == []


def test_a_quote_far_from_its_timestamp_is_a_mismatch(fresh):
    cited_source(fresh)
    concept(fresh, "far-off", body=(
        'They said "Chunking splits a document into retrievable units for indexing." '
        '([Talk](../sources/talk.md) @ 00:00:00)\n'))
    assert kinds(verify.verify_pages(fresh)) == ["timestamp-mismatch"]


def test_a_video_source_with_no_transcript_is_reported(fresh):
    source(fresh, "silent", source_type="video", youtube_id="x", url="u",
           published="2026-08-01", duration="1:00", body="No transcript.\n")
    concept(fresh, "cites-silent", body=(
        'They said "Something long enough to count as a real quotation here." '
        '([Silent](../sources/silent.md) @ 00:01:00)\n'))
    assert kinds(verify.verify_pages(fresh)) == ["no-transcript"]


def test_an_article_without_a_transcript_is_not_reported(fresh):
    source(fresh, "essay", source_type="article", body="An essay.\n")
    concept(fresh, "cites-essay", body=(
        'It says "Something long enough to count as a real quotation here." '
        '([Essay](../sources/essay.md) @ 00:01:00)\n'))
    # articles legitimately have no transcript; that is not a failure
    assert verify.verify_pages(fresh) == []


def test_pages_under_raw_and_candidates_are_not_scanned(fresh):
    cited_source(fresh)
    # a transcript that happens to contain a citation must not be checked as a page
    (fresh.kb / "raw" / "decoy.md").write_text(
        'said "never spoken words at all here truly" '
        '([Talk](../sources/talk.md) @ 00:01:00)\n', encoding="utf-8")
    assert verify.verify_pages(fresh) == []


def test_a_page_with_no_citations_is_skipped(fresh):
    cited_source(fresh)
    concept(fresh, "plain", body="Prose with no citations at all.\n")
    assert verify.verify_pages(fresh) == []


# ---------------------------------------------------------------------------
# verify — both passes
# ---------------------------------------------------------------------------

def test_verify_runs_candidates_before_pages(fresh):
    cited_source(fresh)
    candidate(fresh, concepts=[{
        "title": "X", "verbatim_quote": "not in the transcript anywhere at all",
        "timestamp": "00:01:00"}])
    concept(fresh, "bad-page", body=(
        'They said "Also entirely absent from the transcript, at length." '
        '([Talk](../sources/talk.md) @ 00:01:00)\n'))
    issues = verify.verify(fresh)
    assert len(issues) == 2
    # candidate defects come first: they are upstream of the page they would become
    assert issues[0].file.endswith(".json")
    # page issues carry a line number so the location is clickable
    assert issues[1].file.startswith("concepts/bad-page.md:")


def test_verify_is_empty_on_a_clean_kb(populated):
    assert verify.verify(populated) == []


def test_verify_never_writes_to_the_kb(fresh):
    cited_source(fresh)
    candidate(fresh, concepts=[{
        "title": "X", "verbatim_quote": "absent text here", "timestamp": "00:01:00"}])
    before = {p: p.read_bytes() for p in fresh.kb.rglob("*")if p.is_file()}
    verify.verify(fresh)
    assert {p: p.read_bytes() for p in fresh.kb.rglob("*") if p.is_file()} == before


def test_quote_issue_kinds_are_a_closed_vocabulary(fresh):
    """Every kind this module emits must be one the docstring documents."""
    documented = {"not-verbatim", "timestamp-missing", "timestamp-mismatch",
                  "no-transcript"}
    cited_source(fresh)
    candidate(fresh, concepts=[
        {"title": "a", "verbatim_quote": "nowhere in the transcript", "timestamp": "00:01:00"},
        {"title": "b", "verbatim_quote": "Chunking splits a document", "timestamp": "00:01:00"},
        {"title": "c", "verbatim_quote": "Hybrid retrieval combines lexical and semantic search.",
         "timestamp": "09:00:00"},
    ])
    assert set(kinds(verify.verify(fresh))) <= documented
