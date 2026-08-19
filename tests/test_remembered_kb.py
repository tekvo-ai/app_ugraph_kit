"""Once a machine has a knowledge base, every session should find it.

The precedence these tests pin: anything describing *this* invocation — a flag, an
env var, a nearby ugraph.toml, standing inside a KB — beats the machine-wide
default. The remembered path is the last resort before failing, never the first.
"""

from __future__ import annotations

import pytest
from conftest import scaffold

from ugraph import auth
from ugraph import config as config_mod


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("UGRAPH_KB", raising=False)


@pytest.fixture()
def elsewhere(tmp_path):
    """A directory that is not a KB and contains no ugraph.toml."""
    path = tmp_path / "elsewhere"
    path.mkdir()
    return path


# --- storing ----------------------------------------------------------------

def test_nothing_is_remembered_to_begin_with():
    assert auth.get_kb() is None


def test_set_and_get_round_trip(tmp_path):
    kb = scaffold(tmp_path / "kb").kb
    auth.set_kb(kb)
    assert auth.get_kb() == kb.resolve()


def test_the_path_is_stored_absolute(tmp_path, monkeypatch):
    kb = scaffold(tmp_path / "kb").kb
    monkeypatch.chdir(tmp_path)
    auth.set_kb("kb")
    assert auth.get_kb() == kb.resolve()


def test_a_remembered_path_that_no_longer_exists_reads_as_unset(tmp_path):
    kb = scaffold(tmp_path / "kb").kb
    auth.set_kb(kb)
    import shutil
    shutil.rmtree(kb)
    # a stale default must never be the reason an unrelated command fails
    assert auth.get_kb() is None


def test_forget_clears_it(tmp_path):
    auth.set_kb(scaffold(tmp_path / "kb").kb)
    auth.forget_kb()
    assert auth.get_kb() is None


def test_remembering_a_kb_leaves_the_backend_settings_alone(tmp_path):
    auth.set_backend("api", model="claude-opus-5", provider="anthropic")
    auth.set_kb(scaffold(tmp_path / "kb").kb)
    assert auth.get_backend() == {
        "backend": "api", "model": "claude-opus-5", "provider": "anthropic"}


def test_auth_status_reports_it(tmp_path):
    kb = scaffold(tmp_path / "kb").kb
    auth.set_kb(kb)
    assert auth.status()["kb"] == str(kb.resolve())


# --- resolution -------------------------------------------------------------

def test_a_remembered_kb_is_found_from_an_unrelated_directory(tmp_path, elsewhere,
                                                              monkeypatch):
    kb = scaffold(tmp_path / "kb").kb
    auth.set_kb(kb)
    monkeypatch.chdir(elsewhere)
    assert config_mod.load().kb == kb.resolve()


def test_without_a_remembered_kb_that_directory_still_fails(elsewhere, monkeypatch):
    monkeypatch.chdir(elsewhere)
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load()
    assert "ugraph use" in str(exc.value)


def test_an_explicit_kb_beats_the_remembered_one(tmp_path, elsewhere, monkeypatch):
    remembered = scaffold(tmp_path / "remembered").kb
    asked_for = scaffold(tmp_path / "asked_for").kb
    auth.set_kb(remembered)
    monkeypatch.chdir(elsewhere)
    assert config_mod.load(kb=asked_for).kb == asked_for.resolve()


def test_the_env_var_beats_the_remembered_one(tmp_path, elsewhere, monkeypatch):
    remembered = scaffold(tmp_path / "remembered").kb
    from_env = scaffold(tmp_path / "from_env").kb
    auth.set_kb(remembered)
    monkeypatch.setenv("UGRAPH_KB", str(from_env))
    monkeypatch.chdir(elsewhere)
    assert config_mod.load().kb == from_env.resolve()


def test_standing_inside_a_kb_beats_the_remembered_one(tmp_path, monkeypatch):
    remembered = scaffold(tmp_path / "remembered").kb
    local = scaffold(tmp_path / "local").kb
    auth.set_kb(remembered)
    monkeypatch.chdir(local)
    assert config_mod.load().kb == local.resolve()


def test_a_nearby_ugraph_toml_beats_the_remembered_one(tmp_path, monkeypatch):
    remembered = scaffold(tmp_path / "remembered").kb
    project = tmp_path / "project"
    scaffold(project / "kb")
    (project / "ugraph.toml").write_text('kb = "kb"\n', encoding="utf-8")
    auth.set_kb(remembered)
    monkeypatch.chdir(project)
    assert config_mod.load().kb == (project / "kb").resolve()


def test_the_remembered_kb_brings_its_own_settings(tmp_path, elsewhere, monkeypatch):
    """Falling back must not inherit the settings of whatever directory we stood in."""
    home = tmp_path / "home"
    scaffold(home / "kb")
    (home / "ugraph.toml").write_text(
        'kb = "kb"\n\n[extract]\nmodel = "claude-opus-5"\nmax_tokens = 4242\n',
        encoding="utf-8")
    auth.set_kb(home / "kb")
    monkeypatch.chdir(elsewhere)
    cfg = config_mod.load()
    assert cfg.kb == (home / "kb").resolve()
    assert cfg.raw["extract"]["max_tokens"] == 4242


def test_an_unreadable_settings_file_does_not_break_resolution(tmp_path, monkeypatch):
    kb = scaffold(tmp_path / "kb").kb
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg" / "settings.toml").write_text("{{{ not toml", encoding="utf-8")
    monkeypatch.chdir(kb)
    # config resolution runs on every command; a bad settings file must degrade
    assert config_mod.load().kb == kb.resolve()
