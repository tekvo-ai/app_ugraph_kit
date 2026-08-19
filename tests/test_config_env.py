"""UGRAPH_KB must resolve ugraph.toml beside the KB it names — same as --kb."""

from __future__ import annotations

from ugraph import config as config_mod


def test_env_kb_honors_vault_toml(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    kb = vault / "04_learning"
    kb.mkdir(parents=True)
    (vault / "ugraph.toml").write_text(
        'kb = "04_learning"\ncandidates = "../09_ai_agents/candidates"\n'
    )
    monkeypatch.setenv("UGRAPH_KB", str(kb))
    monkeypatch.chdir(tmp_path)  # cwd has no toml — only the vault does

    cfg = config_mod.load()
    assert cfg.kb == kb.resolve()
    assert cfg.candidates == (vault / "09_ai_agents" / "candidates").resolve()
