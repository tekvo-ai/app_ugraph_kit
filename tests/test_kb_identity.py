"""Every report must say which knowledge base it describes, and why that one.

Once a knowledge base can be resolved from a machine-wide default, a screen of
numbers with no path on it is ambiguous — the reader cannot tell whether they are
looking at the base they meant. These tests pin both halves: the path, and the
reason it was chosen.
"""

from __future__ import annotations

import pytest
from conftest import scaffold

from ugraph import auth
from ugraph import config as config_mod
from ugraph import status as status_mod


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("UGRAPH_KB", raising=False)


# --- Config records why -----------------------------------------------------

def test_an_explicit_flag_is_named(tmp_path):
    kb = scaffold(tmp_path / "kb").kb
    assert config_mod.load(kb=kb).source == "--kb flag"


def test_the_env_var_is_named(tmp_path, monkeypatch):
    kb = scaffold(tmp_path / "kb").kb
    monkeypatch.setenv("UGRAPH_KB", str(kb))
    assert config_mod.load().source == "UGRAPH_KB"


def test_standing_in_a_kb_is_named(tmp_path, monkeypatch):
    kb = scaffold(tmp_path / "kb").kb
    monkeypatch.chdir(kb)
    assert config_mod.load().source == "current directory"


def test_a_config_file_names_its_own_path(tmp_path, monkeypatch):
    project = tmp_path / "project"
    scaffold(project / "kb")
    (project / "ugraph.toml").write_text('kb = "kb"\n', encoding="utf-8")
    monkeypatch.chdir(project)
    assert config_mod.load().source.endswith("ugraph.toml")


def test_the_remembered_default_is_named(tmp_path, monkeypatch):
    kb = scaffold(tmp_path / "kb").kb
    auth.set_kb(kb)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert config_mod.load().source == "remembered default"


# --- status reports it ------------------------------------------------------

def test_collect_carries_the_kb_and_its_source(tmp_path):
    config = scaffold(tmp_path / "kb")
    config = config_mod.load(kb=config.kb)
    stats = status_mod.collect(config)
    assert stats["kb"] == str(config.kb)
    assert stats["kb_source"] == "--kb flag"


def test_the_rendered_header_shows_the_path(tmp_path):
    config = config_mod.load(kb=scaffold(tmp_path / "kb").kb)
    rendered = status_mod.render(status_mod.collect(config))
    assert str(config.kb) in rendered
    assert "via --kb flag" in rendered


def test_a_remembered_default_says_how_to_change_it(tmp_path, monkeypatch):
    kb = scaffold(tmp_path / "kb").kb
    auth.set_kb(kb)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    rendered = status_mod.render(status_mod.collect(config_mod.load()))
    assert "via remembered default" in rendered
    assert "ugraph use PATH" in rendered


def test_other_sources_do_not_get_the_change_hint(tmp_path):
    config = config_mod.load(kb=scaffold(tmp_path / "kb").kb)
    rendered = status_mod.render(status_mod.collect(config))
    assert "ugraph use PATH" not in rendered


def test_the_identity_survives_json_output(tmp_path):
    import json

    config = config_mod.load(kb=scaffold(tmp_path / "kb").kb)
    payload = json.loads(json.dumps(status_mod.collect(config), default=str))
    assert payload["kb"] == str(config.kb)
    assert payload["kb_source"] == "--kb flag"


def test_a_config_built_by_hand_renders_without_an_identity(tmp_path):
    """Library callers construct Config directly; that must not crash the renderer."""
    stats = status_mod.collect(scaffold(tmp_path / "kb"))
    assert stats["kb_source"] == ""
    assert "Knowledge Base Status" in status_mod.render(stats)
