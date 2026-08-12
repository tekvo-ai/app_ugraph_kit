"""Provider selection within the api backend (no network — attributes only)."""

from __future__ import annotations

import pytest

from ugraph import auth
from ugraph.extract import ApiBackend


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "cfg"))
    for var in auth.ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)


def test_first_keyed_provider_wins_by_default():
    auth.set_key("openai", "sk-x")
    backend = ApiBackend()
    assert backend.provider == "openai"
    assert backend.model == "gpt-4o-mini"


def test_provider_preference_overrides_order():
    auth.set_key("anthropic", "sk-ant-x")
    auth.set_key("openai", "sk-oai-x")
    assert ApiBackend().provider == "anthropic"  # default order

    auth.set_backend("api", provider="openai")
    backend = ApiBackend()
    assert backend.provider == "openai"
    assert backend.api_key == "sk-oai-x"


def test_preferred_provider_without_key_falls_back():
    auth.set_key("openai", "sk-oai-x")
    auth.set_backend("api", provider="anthropic")  # pinned but no key for it
    assert ApiBackend().provider == "openai"
