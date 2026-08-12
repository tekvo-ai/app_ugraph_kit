from __future__ import annotations

import os
import stat

import pytest

from ugraph import auth


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "ugraph-config"))
    for var in auth.ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)


def test_set_and_get_key_roundtrip():
    auth.set_key("openai", "sk-test-123")
    assert auth.get_key("openai") == "sk-test-123"
    assert auth.get_key("anthropic") is None


def test_keys_file_is_owner_only():
    path = auth.set_key("anthropic", "sk-ant-xyz")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_env_var_beats_file(monkeypatch):
    auth.set_key("openai", "from-file")
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert auth.get_key("openai") == "from-env"
    assert auth.key_source("openai") == "env:OPENAI_API_KEY"


def test_backend_preference_roundtrip():
    assert auth.get_backend() == {}
    auth.set_backend("ollama", model="qwen2.5:14b")
    assert auth.get_backend() == {"backend": "ollama", "model": "qwen2.5:14b"}


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        auth.set_key("gemini", "nope")
