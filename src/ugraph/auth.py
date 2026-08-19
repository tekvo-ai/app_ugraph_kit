"""
auth.py — where model credentials and the default backend live, and how they get there.

The KB config (ugraph.toml) is project knowledge and often committed to git or synced
by Obsidian. API keys are neither — they live in ~/.config/ugraph/, outside every vault,
with the keys file permissioned 0600. Env vars still win, because CI and one-off shells
should not have to write files to work.

    ugraph auth set openai        # prompt (hidden) → ~/.config/ugraph/keys.toml
    ugraph auth use ollama        # default backend for capture/extract
    ugraph auth status            # what is configured, what is reachable, what to do next
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

KEYS_FILE = "keys.toml"
SETTINGS_FILE = "settings.toml"

PROVIDERS = ("anthropic", "openai")
ENV_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}

#: Fallback model per provider, used only when neither `ugraph auth use --model` nor
#: `[extract].model` names one. A default, not a pin: every call site takes the model
#: as a parameter, so upgrading is a config change, never a code change.
DEFAULT_MODELS = {"anthropic": "claude-opus-5", "openai": "gpt-4o-mini"}


#: How an API model announces its provider. Prefix match, longest first so a more
#: specific prefix wins. This is deliberately not an allowlist of known models — it
#: only answers "who serves this?", so a model released tomorrow routes correctly
#: without a code change. Anything unrecognised is not an error: it routes to the
#: local backend, which is the one that can serve an arbitrary name.
MODEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
    ("chatgpt-", "openai"),
    ("text-embedding-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
)


def provider_for_model(model: str | None) -> str | None:
    """Which API provider serves this model ID, or None if no API provider does.

    None means "not an API model as far as we can tell" — the caller should treat it
    as local rather than guessing a provider, because sending a model to the wrong
    API is a confusing failure that looks like a bad key.
    """
    name = str(model or "").strip().lower()
    if not name:
        return None
    for prefix, provider in sorted(MODEL_PREFIXES, key=lambda p: -len(p[0])):
        if name.startswith(prefix):
            return provider
    return None


def backend_for_model(model: str | None) -> str | None:
    """The backend that should run this model: `api`, `ollama`, or None if unnamed."""
    if not str(model or "").strip():
        return None
    return "api" if provider_for_model(model) else "ollama"


def config_dir() -> Path:
    """Resolved per call so tests and shells can override with UGRAPH_CONFIG_HOME."""
    return Path(os.environ.get("UGRAPH_CONFIG_HOME", Path.home() / ".config" / "ugraph"))


def _path(name: str) -> Path:
    return config_dir() / name


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # A hand-edited, malformed keys file should degrade to "not set", not crash
        # an unrelated command — auth status will say so.
        return {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{key} = "{value}"' for key, value in sorted(data.items()) if value]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_key(provider: str, key: str) -> Path:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; expected one of {PROVIDERS}")
    path = _path(KEYS_FILE)
    data = _read(path)
    data[provider] = key.strip()
    _write(path, data)
    path.chmod(0o600)
    return path


def get_key(provider: str) -> str | None:
    """Env var first (CI, one-off shells), then the keys file."""
    env = ENV_VARS.get(provider)
    if env and os.environ.get(env):
        return os.environ[env]
    value = _read(_path(KEYS_FILE)).get(provider)
    return str(value) if value else None


def key_source(provider: str) -> str | None:
    env = ENV_VARS.get(provider)
    if env and os.environ.get(env):
        return f"env:{env}"
    if _read(_path(KEYS_FILE)).get(provider):
        return str(_path(KEYS_FILE))
    return None


def set_backend(name: str, model: str | None = None,
                provider: str | None = None) -> Path:
    path = _path(SETTINGS_FILE)
    data = _read(path)
    data["backend"] = name
    if model:
        data["model"] = model
    if provider:
        data["provider"] = provider
    _write(path, data)
    return path


def get_backend() -> dict[str, str]:
    data = _read(_path(SETTINGS_FILE))
    out: dict[str, str] = {}
    for key in ("backend", "model", "provider"):
        if data.get(key):
            out[key] = str(data[key])
    return out


def set_kb(path: str | Path) -> Path:
    """Remember this knowledge base as the machine default for future sessions."""
    settings = _path(SETTINGS_FILE)
    data = _read(settings)
    data["kb"] = str(Path(path).expanduser().resolve())
    _write(settings, data)
    return settings


def get_kb() -> Path | None:
    """The remembered knowledge base, if one is set and still on disk.

    A remembered path that has since been deleted or moved is treated as unset: it
    should never be the reason a command fails somewhere unrelated.
    """
    value = _read(_path(SETTINGS_FILE)).get("kb")
    if not value:
        return None
    path = Path(str(value)).expanduser()
    return path if path.is_dir() else None


def forget_kb() -> None:
    settings = _path(SETTINGS_FILE)
    data = _read(settings)
    if data.pop("kb", None) is not None:
        _write(settings, data)


def default_model(provider: str) -> str:
    return DEFAULT_MODELS.get(provider, "")


def status() -> dict[str, Any]:
    """Everything `ugraph auth status` prints, as data."""
    kb = get_kb()
    return {
        "config_dir": str(config_dir()),
        "keys": {p: key_source(p) for p in PROVIDERS},
        "backend": get_backend(),
        "kb": str(kb) if kb else None,
    }
