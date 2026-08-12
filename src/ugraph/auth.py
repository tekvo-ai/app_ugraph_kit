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

DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini"}


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


def default_model(provider: str) -> str:
    return DEFAULT_MODELS.get(provider, "")


def status() -> dict[str, Any]:
    """Everything `ugraph auth status` prints, as data."""
    return {
        "config_dir": str(config_dir()),
        "keys": {p: key_source(p) for p in PROVIDERS},
        "backend": get_backend(),
    }
