"""Lifecycle state derived from what is actually on disk.

The rule that matters: stage is the *furthest* point reached, so an unrecorded
earlier step never masks a later one. And a page synthesized without a transcript
behind it is flagged, not quietly counted as progress.
"""

from __future__ import annotations

import json

from conftest import concept, source

from ugraph import ledger

# --- transition log ---------------------------------------------------------

def test_record_appends_one_line_per_transition(populated):
    ledger.record(populated, "retrieval-notes", "pulled", by="test")
    ledger.record(populated, "retrieval-notes", "extracted", by="test")
    lines = ledger.ledger_path(populated).read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["stage"] == "pulled"
    assert json.loads(lines[1])["stage"] == "extracted"


def test_record_stores_slug_stage_and_attribution(populated):
    entry = ledger.record(populated, "a-slug", "pulled", by="ugraph test",
                          detail="3 items")
    assert entry["slug"] == "a-slug"
    assert entry["stage"] == "pulled"
    assert entry["by"] == "ugraph test"
    assert entry["detail"] == "3 items"
    assert entry["ts"]


def test_history_is_empty_before_anything_is_recorded(populated):
    assert ledger.history(populated) == []


def test_history_filters_by_slug(populated):
    ledger.record(populated, "one", "pulled")
    ledger.record(populated, "two", "pulled")
    assert [e["slug"] for e in ledger.history(populated, "one")] == ["one"]
    assert len(ledger.history(populated)) == 2


def test_history_survives_a_corrupt_line(populated):
    ledger.record(populated, "good", "pulled")
    with ledger.ledger_path(populated).open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    ledger.record(populated, "also-good", "pulled")
    slugs = [e["slug"] for e in ledger.history(populated)]
    assert slugs == ["good", "also-good"]


# --- collect ----------------------------------------------------------------

def test_collect_finds_one_item_per_source_page(populated):
    items = ledger.collect(populated)
    assert [i.slug for i in items] == ["retrieval-notes"]


def test_a_source_with_its_transcript_on_disk_is_pulled(populated):
    item = ledger.collect(populated)[0]
    assert item.pulled is True
    assert item.stage == "pulled"


def test_a_source_without_a_transcript_stops_at_discovered(populated):
    source(populated, "no-raw", body="No transcript.\n")
    items = {i.slug: i for i in ledger.collect(populated)}
    assert items["no-raw"].pulled is False
    assert items["no-raw"].stage == "discovered"


def test_a_video_without_a_transcript_is_flagged_but_an_article_is_not(populated):
    source(populated, "silent-video", source_type="video", body="x\n")
    source(populated, "plain-article", source_type="article", body="x\n")
    items = {i.slug: i for i in ledger.collect(populated)}
    assert any("no `raw:` transcript" in msg for msg in items["silent-video"].issues)
    assert items["plain-article"].issues == []


def test_synthesized_without_a_transcript_is_orphaned_not_progress(populated):
    # a source that claims completion, cited by a concept, but never pulled
    source(populated, "claims-only", body="x\n", summary_status="done")
    concept(populated, "cites-it", sources=["claims-only"],
            body="## Related\n\n- [Chunking](chunking.md)\n")
    items = {i.slug: i for i in ledger.collect(populated)}
    item = items["claims-only"]
    assert item.stage == "orphaned"
    assert any("unverifiable" in msg for msg in item.issues)


def test_stage_is_the_furthest_point_reached(populated):
    items = {i.slug: i for i in ledger.collect(populated)}
    item = items["retrieval-notes"]
    # extracted is not reached (no candidate file), so pulled is the max
    assert item.extracted is False
    assert item.stage == "pulled"


def test_a_candidate_file_advances_the_item_to_extracted(populated):
    populated.candidates.mkdir(parents=True, exist_ok=True)
    (populated.candidates / "retrieval-notes.json").write_text("{}", encoding="utf-8")
    item = ledger.collect(populated)[0]
    assert item.extracted is True
    assert item.stage == "extracted"


def test_collect_is_ordered_by_stage_then_slug(populated):
    source(populated, "zzz-no-raw", body="x\n")
    source(populated, "aaa-no-raw", body="x\n")
    stages = [(i.stage, i.slug) for i in ledger.collect(populated)]
    assert stages == sorted(stages, key=lambda s: (ledger.STAGES.index(s[0]), s[1]))


# --- reporting --------------------------------------------------------------

def test_summary_counts_items_by_stage(populated):
    source(populated, "no-raw", body="x\n")
    counts = ledger.summary(ledger.collect(populated))
    assert counts["pulled"] == 1
    assert counts["discovered"] == 1


def test_render_table_says_so_when_there_is_nothing(populated):
    assert "no sources yet" in ledger.render_table([])


def test_render_table_lists_the_slug_and_stage(populated):
    table = ledger.render_table(ledger.collect(populated))
    assert "retrieval-notes" in table
    assert "pulled" in table


def test_render_table_respects_a_limit(populated):
    for n in range(5):
        source(populated, f"extra-{n}", body="x\n")
    table = ledger.render_table(ledger.collect(populated), limit=2)
    assert "and 4 more" in table


def test_to_json_round_trips_every_item(populated):
    items = ledger.collect(populated)
    decoded = json.loads(ledger.to_json(items))
    assert [d["slug"] for d in decoded] == [i.slug for i in items]


def test_write_report_produces_a_readable_page(populated):
    path = ledger.write_report(populated)
    assert path.is_file()
    text = path.read_text()
    # the report is for humans in a vault, so it shows the title, not the slug
    assert "Retrieval Notes" in text
    assert text.startswith("---")     # frontmatter, so a vault renders it


def test_done_and_stuck_describe_the_item(populated):
    item = ledger.collect(populated)[0]
    assert item.done is False
    assert item.stuck is True     # pulled, never synthesized
