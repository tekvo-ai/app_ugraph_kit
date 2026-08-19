"""A model ID should name its own backend and provider.

The property: pointing ugraph at a model it has never heard of must work without a
code change. Nothing here is an allowlist of known models — the tests assert the
routing *rule*, including that an unrecognised name is treated as local rather than
guessed at, and that a routed provider is a requirement rather than a preference.
"""

from __future__ import annotations

import pytest

from ugraph import auth
from ugraph.extract import ApiBackend, BackendError


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# --- the routing rule -------------------------------------------------------

@pytest.mark.parametrize("model,provider", [
    ("claude-opus-5", "anthropic"),
    ("claude-sonnet-5", "anthropic"),
    ("claude-anything-at-all", "anthropic"),
    ("gpt-4o", "openai"),
    ("gpt-99-turbo", "openai"),
    ("o3-mini", "openai"),
    ("chatgpt-4o-latest", "openai"),
])
def test_api_models_route_to_their_provider(model, provider):
    assert auth.provider_for_model(model) == provider
    assert auth.backend_for_model(model) == "api"


@pytest.mark.parametrize("model", [
    "llama3.3:70b", "qwen2.5-coder:7b", "mistral", "deepseek-r1",
    "some-model-shipped-tomorrow",
])
def test_unrecognised_models_are_local_not_guessed(model):
    assert auth.provider_for_model(model) is None
    assert auth.backend_for_model(model) == "ollama"


def test_routing_is_case_insensitive_and_ignores_padding():
    assert auth.provider_for_model("  Claude-Opus-5  ") == "anthropic"


@pytest.mark.parametrize("model", [None, "", "   "])
def test_no_model_routes_nowhere(model):
    assert auth.provider_for_model(model) is None
    assert auth.backend_for_model(model) is None


def test_a_longer_prefix_wins_over_a_shorter_one():
    # guards the sort in provider_for_model against a future overlapping prefix
    assert auth.provider_for_model("text-embedding-3-small") == "openai"


# --- the routed provider is binding ----------------------------------------

def test_the_model_overrides_a_pinned_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    auth.set_backend("api", provider="anthropic")   # pinned to anthropic
    assert ApiBackend(model="gpt-4o").provider == "openai"


def test_a_routed_model_never_falls_back_to_the_other_key(monkeypatch):
    """The bug this prevents: gpt-4o sent to Anthropic, failing as an auth error."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")   # only anthropic configured
    backend = ApiBackend(model="gpt-4o")
    assert backend.provider == "openai"
    assert backend.api_key is None
    with pytest.raises(BackendError) as exc:
        backend.check()
    message = str(exc.value)
    assert "openai" in message
    assert "gpt-4o" in message


def test_an_unrouted_model_still_uses_whichever_key_exists(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    # no prefix match, so provider selection falls back to available keys
    assert ApiBackend(model="my-finetune-v3").provider == "openai"


def test_a_pinned_provider_still_applies_when_the_model_says_nothing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    auth.set_backend("api", provider="openai")
    assert ApiBackend().provider == "openai"


def test_an_arbitrary_model_is_used_verbatim(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    assert ApiBackend(model="claude-something-unreleased").model == (
        "claude-something-unreleased")
