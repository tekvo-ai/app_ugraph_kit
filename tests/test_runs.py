"""The runs stream: jobs emit, ps/logs read. Observability P0 contract."""

from __future__ import annotations

import json

from ugraph import ingest as ingest_mod
from ugraph import runs
from ugraph.extract import Backend, extract_document

DOC = "Alpha paragraph about retrieval.\n\nBeta paragraph about evaluation."


class FakeBackend(Backend):
    name = "fake"

    def complete(self, system: str, user: str) -> str:
        return json.dumps({
            "yield": "low",
            "concepts": [
                {"name": "alpha", "claim": "c",
                 "verbatim_quote": "Alpha paragraph about retrieval."},
            ],
        })


def test_run_context_emits_start_and_done(cfg):
    with runs.Run(cfg, "ingest", "doc-a", source_type="copy-paste") as run:
        run.stage("chunks", items_done=2, items_total=2)

    events = runs.read(cfg)
    kinds = [(e["event"], e.get("step")) for e in events]
    assert kinds[0] == ("start", None)
    assert ("stage", "chunks") in kinds
    assert kinds[-1] == ("done", None)
    assert all(e["run"] == run.id for e in events)
    assert events[-1]["elapsed_ms"] >= 0


def test_run_fail_marks_once(cfg):
    with runs.Run(cfg, "extract", "doc-b") as run:
        run.fail("gate rejected everything")
    events = [e["event"] for e in runs.read(cfg)]
    assert events == ["start", "fail"]


def test_ingest_document_emits_run(cfg):
    ingest_mod.ingest_document(cfg, DOC, slug="doc-c", title="Doc C")
    trail = runs.for_slug(cfg, "doc-c")
    assert trail[0]["event"] == "start"
    assert any(e.get("step") == "chunks" and e.get("items_total") == 2 for e in trail)
    assert trail[-1]["event"] == "done"


def test_extract_document_emits_gate_stage(cfg):
    ingest_mod.ingest_document(cfg, DOC, slug="doc-d", title="Doc D")
    extract_document(cfg, "doc-d", FakeBackend())
    trail = runs.for_slug(cfg, "doc-d")
    extract_events = [e for e in trail if e["module"] == "extract"]
    assert any(e.get("step") == "gate" and e.get("kept") == 1 for e in extract_events)
    assert any(e.get("step") == "write" for e in extract_events)
    assert extract_events[-1]["event"] == "done"


def test_latest_per_run_marks_active(cfg):
    runs.emit(cfg, "extract", "start", run="live1", slug="doc-e")
    runs.emit(cfg, "extract", "start", run="dead1", slug="doc-f")
    runs.emit(cfg, "extract", "done", run="dead1", slug="doc-f", elapsed_ms=5)

    rows = {r["run"]: r for r in runs.latest_per_run(cfg)}
    assert rows["live1"]["active"] is True
    assert rows["live1"]["elapsed_ms"] >= 0
    assert rows["dead1"]["active"] is False


def test_read_tolerates_torn_last_line(cfg):
    path = cfg.state / runs.RUNS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"event": "start"}\n{"event": "sta', encoding="utf-8")
    assert len(runs.read(cfg)) == 1
