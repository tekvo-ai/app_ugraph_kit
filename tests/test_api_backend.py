"""What ApiBackend actually puts on the wire.

The regression these guard: a token ceiling hardcoded in the call site. Every
assertion here checks that the budget came from config, discovery, or derivation —
and that knobs the operator did not set are absent from the request rather than
filled in with a value this codebase chose.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ugraph import limits
from ugraph.config import Config
from ugraph.extract import ApiBackend


class _FakeStream:
    """The `with client.messages.stream(...)` shape. Dunders must live on the type."""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def get_final_message(self):
        text = SimpleNamespace(type="text", text='{"yield":"low","concepts":[]}')
        return SimpleNamespace(content=[text])


class Recorder:
    """A stand-in provider client that records the request instead of sending it."""

    def __init__(self, max_tokens=None, max_input_tokens=None):
        self.request = None
        info = SimpleNamespace(max_tokens=max_tokens, max_input_tokens=max_input_tokens)
        self.models = SimpleNamespace(retrieve=lambda _m: info)
        # anthropic surface
        self.messages = SimpleNamespace(stream=self._stream)
        # openai surface
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create))

    def _stream(self, **request):
        self.request = request
        return _FakeStream()

    def _create(self, **request):
        self.request = request
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="{}"))])


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    """An ApiBackend wired to a recorder, with auth and the cache pointed at tmp."""
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def build(client, **extract_settings):
        config = Config(kb=tmp_path / "kb", raw={"extract": extract_settings})
        api = ApiBackend(model="a-model", config=config)
        api._client = lambda: client
        return api

    return build


# --- the budget -------------------------------------------------------------

def test_the_budget_comes_from_the_provider_when_it_reports_one(backend):
    client = Recorder(max_tokens=64_000)
    backend(client).complete("sys", "user text")
    assert client.request["max_tokens"] == 64_000


def test_operator_config_overrides_the_provider(backend):
    client = Recorder(max_tokens=64_000)
    backend(client, max_tokens=9_000).complete("sys", "user text")
    assert client.request["max_tokens"] == 9_000


def test_the_budget_is_derived_when_the_provider_reports_nothing(backend):
    client = Recorder()  # no ceilings published
    backend(client).complete("sys", "a short prompt")
    assert client.request["max_tokens"] == limits.MIN_OUTPUT_TOKENS


def test_the_derived_budget_grows_with_the_prompt(backend):
    small, large = Recorder(), Recorder()
    backend(small).complete("sys", "short")
    backend(large).complete("sys", "word " * 100_000)
    assert large.request["max_tokens"] > small.request["max_tokens"]


def test_a_nonsense_configured_budget_is_ignored_rather_than_sent(backend):
    client = Recorder(max_tokens=64_000)
    backend(client, max_tokens="not a number").complete("sys", "user")
    assert client.request["max_tokens"] == 64_000


def test_a_zero_or_negative_configured_budget_is_ignored(backend):
    client = Recorder(max_tokens=64_000)
    backend(client, max_tokens=0).complete("sys", "user")
    assert client.request["max_tokens"] == 64_000


# --- unset knobs stay off the wire ------------------------------------------

def test_thinking_and_effort_are_absent_unless_configured(backend):
    client = Recorder(max_tokens=1000)
    backend(client).complete("sys", "user")
    assert "thinking" not in client.request
    assert "output_config" not in client.request
    assert "temperature" not in client.request


def test_configured_thinking_and_effort_are_passed_through(backend):
    client = Recorder(max_tokens=1000)
    backend(client, thinking="disabled", effort="low").complete("sys", "user")
    assert client.request["thinking"] == {"type": "disabled"}
    assert client.request["output_config"] == {"effort": "low"}


def test_configured_temperature_is_passed_through(backend):
    client = Recorder(max_tokens=1000)
    backend(client, temperature=0.1).complete("sys", "user")
    assert client.request["temperature"] == 0.1


# --- transport --------------------------------------------------------------

def test_the_anthropic_path_streams(backend):
    """Streaming is what makes a large discovered ceiling safe to request."""
    client = Recorder(max_tokens=128_000)
    backend(client).complete("sys", "user")
    # the recorder only records via messages.stream, so a captured request proves it
    assert client.request is not None
    assert client.request["max_tokens"] == 128_000


def test_the_text_blocks_are_joined(backend):
    assert backend(Recorder(max_tokens=1000)).complete("sys", "user") == (
        '{"yield":"low","concepts":[]}')


# --- openai omits the ceiling ----------------------------------------------

def test_openai_omits_max_tokens_so_the_provider_applies_its_own_maximum(
        tmp_path, monkeypatch):
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = Recorder()
    api = ApiBackend(model="gpt-x", config=Config(kb=tmp_path / "kb"))
    api._client = lambda: client
    assert api.provider == "openai"
    api.complete("sys", "user")
    assert "max_completion_tokens" not in client.request
    assert "max_tokens" not in client.request


def test_openai_sends_a_configured_ceiling_as_max_completion_tokens(
        tmp_path, monkeypatch):
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = Recorder()
    config = Config(kb=tmp_path / "kb", raw={"extract": {"max_tokens": 5000}})
    api = ApiBackend(model="gpt-x", config=config)
    api._client = lambda: client
    api.complete("sys", "user")
    assert client.request["max_completion_tokens"] == 5000


# --- no config at all -------------------------------------------------------

def test_a_backend_built_without_config_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = Recorder(max_tokens=32_000)
    api = ApiBackend(model="a-model")
    api._client = lambda: client
    api.complete("sys", "user")
    assert client.request["max_tokens"] == 32_000
