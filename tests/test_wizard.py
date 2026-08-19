"""The interactive `ugraph init` — a user's first sixty seconds.

The wizard used to open by asking for a YouTube channel, which contradicted the
product's own pitch ("copy anything, type ugraph"). These tests pin the flow as
source-agnostic, and pin the two things it must never get wrong: writing a stale
repository URL into every generated config, and blocking when there is no terminal.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from ugraph import wizard


def answer(monkeypatch, *responses):
    """Feed the wizard a scripted sequence of prompt answers."""
    supply = iter(responses)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(supply))


def run_quietly(cwd) -> dict:
    with redirect_stdout(io.StringIO()):
        return wizard.run(cwd=cwd)


# --- prompting primitives ---------------------------------------------------

def test_ask_returns_the_default_on_an_empty_answer(monkeypatch):
    answer(monkeypatch, "")
    assert wizard.ask("Knowledge base folder", "knowledge") == "knowledge"


def test_ask_strips_whitespace(monkeypatch):
    answer(monkeypatch, "  mykb  ")
    assert wizard.ask("folder", "knowledge") == "mykb"


def test_ask_exits_cleanly_on_ctrl_d(monkeypatch):
    def raise_eof(_prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", raise_eof)
    with redirect_stdout(io.StringIO()), pytest.raises(SystemExit) as exc:
        wizard.ask("folder")
    assert exc.value.code == 130


def test_ask_choice_reprompts_until_the_number_is_in_range(monkeypatch):
    answer(monkeypatch, "99", "0", "abc", "2")
    with redirect_stdout(io.StringIO()):
        chosen = wizard.ask_choice("Which?", wizard.BACKENDS, default=1)
    assert chosen == wizard.BACKENDS[1][0]


def test_ask_choice_default_is_used_on_an_empty_answer(monkeypatch):
    answer(monkeypatch, "")
    with redirect_stdout(io.StringIO()):
        assert wizard.ask_choice("Which?", wizard.BACKENDS, default=1) == "claude-code"


# --- interactive() ----------------------------------------------------------

def test_interactive_is_false_when_stdin_is_not_a_terminal(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("piped"))
    assert wizard.interactive() is False


# --- vault detection --------------------------------------------------------

def test_find_vault_detects_obsidian_logseq_and_foam(tmp_path):
    for marker in (".obsidian", ".logseq", ".foam"):
        root = tmp_path / marker.lstrip(".")
        (root / marker).mkdir(parents=True)
        assert wizard.find_vault(root) == root.resolve()


def test_find_vault_walks_upward(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert wizard.find_vault(nested) == tmp_path.resolve()


def test_find_vault_returns_none_outside_a_vault(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert wizard.find_vault(plain) is None


# --- the source question is source-agnostic ---------------------------------

def test_a_file_path_is_accepted_as_a_source(monkeypatch, tmp_path):
    answer(monkeypatch, "knowledge", "./notes.md", "4")
    answers = run_quietly(tmp_path)
    assert answers["source"] == "./notes.md"


def test_a_file_path_is_not_asked_how_many_videos(monkeypatch, tmp_path):
    answer(monkeypatch, "knowledge", "./notes.md", "4")
    answers = run_quietly(tmp_path)
    # "how many videos" is meaningless for a single file; asking it would consume the
    # backend answer and silently mis-configure the KB
    assert "limit" not in answers


def test_a_feed_url_is_asked_how_many_videos(monkeypatch, tmp_path):
    answer(monkeypatch, "knowledge", "https://youtube.com/@example/videos", "10", "4")
    answers = run_quietly(tmp_path)
    assert answers["limit"] == 10
    assert answers["backend"] == "later"


def test_a_non_numeric_video_count_falls_back_to_a_default(monkeypatch, tmp_path):
    answer(monkeypatch, "knowledge", "https://youtube.com/@example/videos", "lots", "4")
    assert run_quietly(tmp_path)["limit"] == 25


def test_the_source_question_may_be_skipped(monkeypatch, tmp_path):
    answer(monkeypatch, "knowledge", "", "4")
    assert run_quietly(tmp_path)["source"] is None


def test_the_kb_never_lands_on_the_vault_root(monkeypatch, tmp_path):
    (tmp_path / ".obsidian").mkdir()
    answer(monkeypatch, ".", "", "4")
    answers = run_quietly(tmp_path)
    assert answers["kb"] != tmp_path.resolve()
    assert answers["kb"].name == "knowledge"


def test_is_feed_url_only_matches_feeds_not_person_links():
    assert wizard.is_feed_url("https://youtube.com/@example/videos") is True
    assert wizard.is_feed_url("https://youtube.com/playlist?list=PL1") is True
    # a bare handle resolves to a *person*, not a feed with a backlog
    assert wizard.is_feed_url("https://youtube.com/@example") is False
    assert wizard.is_feed_url("./notes.md") is False


# --- generated config -------------------------------------------------------

def test_the_generated_config_points_at_the_canonical_repository(tmp_path):
    toml = wizard.toml_for({"kb": tmp_path / "kb"}, tmp_path / "ugraph.toml")
    assert "tekvo-ai/app_ugraph_kit" in toml
    assert "saran-io" not in toml


def test_the_generated_config_uses_a_relative_kb_when_it_can(tmp_path):
    toml = wizard.toml_for({"kb": tmp_path / "kb"}, tmp_path / "ugraph.toml")
    assert 'kb = "kb"' in toml


def test_the_generated_config_falls_back_to_an_absolute_kb(tmp_path):
    elsewhere = tmp_path / "elsewhere" / "kb"
    toml = wizard.toml_for({"kb": elsewhere}, tmp_path / "nested" / "ugraph.toml")
    assert str(elsewhere) in toml


def test_a_chosen_backend_is_written_to_the_config(tmp_path):
    toml = wizard.toml_for({"kb": tmp_path / "kb", "backend": "ollama"},
                           tmp_path / "ugraph.toml")
    assert "[extract]" in toml
    assert 'backend = "ollama"' in toml
    assert "qwen2.5-coder:7b" in toml


def test_deciding_later_writes_no_extract_section(tmp_path):
    toml = wizard.toml_for({"kb": tmp_path / "kb", "backend": "later"},
                           tmp_path / "ugraph.toml")
    assert "[extract]" not in toml


def test_the_config_ends_with_exactly_one_newline(tmp_path):
    toml = wizard.toml_for({"kb": tmp_path / "kb"}, tmp_path / "ugraph.toml")
    assert toml.endswith("\n")
    assert not toml.endswith("\n\n")


# --- summary ----------------------------------------------------------------

def base(tmp_path, **extra):
    return {"kb": tmp_path / "kb", "backend": "later", **extra}


def test_the_summary_leads_with_the_daily_loop(tmp_path):
    lines = wizard.summary(base(tmp_path), tmp_path / "ugraph.toml").splitlines()
    next_index = lines.index("  Next:")
    first_command = lines[next_index + 1]
    assert first_command.strip().startswith("ugraph ")
    assert "clipboard" in first_command


def test_the_summary_offers_both_input_kinds_when_nothing_was_ingested(tmp_path):
    text = wizard.summary(base(tmp_path), tmp_path / "ugraph.toml")
    assert "ugraph ingest file" in text
    assert "ugraph ingest youtube" in text


def test_the_summary_reports_what_was_ingested(tmp_path):
    text = wizard.summary(base(tmp_path, source="./notes.md"), tmp_path / "ugraph.toml")
    assert "Ingested from    ./notes.md" in text
    # already done, so it must not also tell them to go do it
    assert "ugraph ingest file ./notes.md" not in text


def test_a_failed_ingest_repeats_the_exact_retry_command(tmp_path):
    text = wizard.summary(
        base(tmp_path, source=None, retry_command="ugraph ingest file ./notes.md"),
        tmp_path / "ugraph.toml")
    assert "ugraph ingest file ./notes.md" in text
    # and not a placeholder they would have to fill in again
    assert "<channel-or-playlist-url>" not in text


def test_each_backend_gets_its_own_next_steps(tmp_path):
    ollama = wizard.summary(base(tmp_path, backend="ollama"), tmp_path / "t.toml")
    assert "ollama pull" in ollama
    api = wizard.summary(base(tmp_path, backend="api"), tmp_path / "t.toml")
    assert "ANTHROPIC_API_KEY" in api
    claude = wizard.summary(base(tmp_path, backend="claude-code"), tmp_path / "t.toml")
    assert "skills install" in claude


def test_the_summary_never_mentions_youtube_as_the_headline(tmp_path):
    text = wizard.summary(base(tmp_path, source="./notes.md"), tmp_path / "ugraph.toml")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    next_index = next(i for i, ln in enumerate(lines) if ln.strip() == "Next:")
    assert "youtube" not in lines[next_index + 1].lower()
