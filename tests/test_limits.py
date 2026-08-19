"""Token budgets are discovered, cached, or derived — never written into the code.

The property these tests defend: swapping the model must not require a code change.
Every path here resolves a ceiling without any test naming a token count for a
specific model, which is the same guarantee the production path relies on.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from ugraph import limits


class FakeModels:
    """A provider `client.models` that reports whatever the test wants."""

    def __init__(self, info=None, raises=None):
        self._info, self._raises, self.calls = info, raises, 0

    def retrieve(self, model):
        self.calls += 1
        if self._raises:
            raise self._raises
        return self._info


def client_with(info=None, raises=None):
    return SimpleNamespace(models=FakeModels(info, raises))


# --- discovery --------------------------------------------------------------

def test_discover_reads_the_ceilings_the_provider_reports():
    client = client_with(SimpleNamespace(max_tokens=128_000, max_input_tokens=1_000_000))
    found = limits.discover(client, "some-model")
    assert found.max_output_tokens == 128_000
    assert found.max_input_tokens == 1_000_000
    assert found.source == "provider"


def test_discover_returns_none_when_the_provider_publishes_no_ceilings():
    # OpenAI's model object has no output cap; that is a fall-through, not an error
    assert limits.discover(client_with(SimpleNamespace(id="gpt-x")), "gpt-x") is None


def test_discover_returns_none_when_the_provider_cannot_be_reached():
    assert limits.discover(client_with(raises=OSError("offline")), "m") is None


def test_discover_returns_none_when_the_client_has_no_models_api():
    assert limits.discover(SimpleNamespace(), "m") is None


def test_discover_accepts_a_partial_answer():
    client = client_with(SimpleNamespace(max_input_tokens=200_000))
    found = limits.discover(client, "m")
    assert found.max_output_tokens is None
    assert found.max_input_tokens == 200_000


# --- cache ------------------------------------------------------------------

def test_a_discovered_limit_is_remembered_and_reused(tmp_path):
    found = limits.ModelLimits("m", max_output_tokens=64_000, source="provider")
    limits.remember(tmp_path, "anthropic", found)
    hit = limits.cached(tmp_path, "anthropic", "m")
    assert hit.max_output_tokens == 64_000
    assert hit.source == "cache"


def test_the_cache_is_keyed_by_provider_and_model(tmp_path):
    limits.remember(tmp_path, "anthropic", limits.ModelLimits("m", max_output_tokens=1))
    assert limits.cached(tmp_path, "openai", "m") is None
    assert limits.cached(tmp_path, "anthropic", "other") is None


def test_a_stale_entry_is_a_miss(tmp_path):
    limits.remember(tmp_path, "anthropic", limits.ModelLimits("m", max_output_tokens=1),
                    now=1000.0)
    assert limits.cached(tmp_path, "anthropic", "m", now=1000.0, ttl=60) is not None
    assert limits.cached(tmp_path, "anthropic", "m", now=9999.0, ttl=60) is None


def test_a_corrupt_cache_is_a_miss_not_a_crash(tmp_path):
    limits.cache_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert limits.cached(tmp_path, "anthropic", "m") is None


def test_remembering_one_model_preserves_the_others(tmp_path):
    limits.remember(tmp_path, "anthropic", limits.ModelLimits("a", max_output_tokens=1))
    limits.remember(tmp_path, "anthropic", limits.ModelLimits("b", max_output_tokens=2))
    stored = json.loads(limits.cache_path(tmp_path).read_text())
    assert set(stored) == {"anthropic:a", "anthropic:b"}


def test_an_unwritable_cache_dir_does_not_fail_the_lookup(tmp_path):
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory", encoding="utf-8")
    # remember() must swallow this: losing the cache costs one request, not a run
    limits.remember(blocked / "sub", "anthropic", limits.ModelLimits("m", 1))


# --- derived budget ---------------------------------------------------------

def test_the_derived_budget_scales_with_the_prompt():
    small = limits.derive_output_budget("sys", "a short note")
    large = limits.derive_output_budget("sys", "word " * 200_000)
    assert large > small


def test_the_derived_budget_never_drops_below_the_floor():
    assert limits.derive_output_budget("", "") == limits.MIN_OUTPUT_TOKENS


def test_the_derived_budget_respects_a_known_ceiling():
    budget = limits.derive_output_budget("sys", "word " * 200_000, ceiling=10_000)
    assert budget == 10_000


# --- resolve ----------------------------------------------------------------

def test_operator_config_outranks_everything(tmp_path):
    client = client_with(SimpleNamespace(max_tokens=128_000))
    found = limits.resolve("anthropic", "m", config_dir=tmp_path,
                           client=client, configured=1234)
    assert found.max_output_tokens == 1234
    assert found.source == "config"
    assert client.models.calls == 0, "an explicit ceiling must not cost a request"


def test_resolve_discovers_once_then_serves_from_cache(tmp_path):
    client = client_with(SimpleNamespace(max_tokens=64_000, max_input_tokens=200_000))
    first = limits.resolve("anthropic", "m", config_dir=tmp_path, client=client)
    second = limits.resolve("anthropic", "m", config_dir=tmp_path, client=client)
    assert first.source == "provider"
    assert second.source == "cache"
    assert second.max_output_tokens == 64_000
    assert client.models.calls == 1


def test_resolve_falls_through_to_unknown_when_nothing_can_answer(tmp_path):
    found = limits.resolve("openai", "m", config_dir=tmp_path,
                           client=client_with(SimpleNamespace(id="m")))
    assert found.max_output_tokens is None
    assert found.source == "unknown"


def test_resolve_works_with_no_client_at_all(tmp_path):
    found = limits.resolve("anthropic", "m", config_dir=tmp_path)
    assert found.max_output_tokens is None
