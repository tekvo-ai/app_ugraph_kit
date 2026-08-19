# Security policy

## Supported versions

ugraph is alpha software. Only the latest released version on PyPI
(`ugraph-kit`) receives security fixes.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/tekvo-ai/app_ugraph_kit/security/advisories/new)
on this repository. Include what you ran, what you observed, and the impact you think
it has. Expect an initial response within a week.

## What ugraph touches on your machine

Worth knowing when assessing impact:

- **API keys** are stored in `~/.config/ugraph/` with mode `0600`, never in the
  `ugraph.toml` that lives inside your (often committed) vault. Environment variables
  take precedence over stored keys.
- **ugraph shells out** to `yt-dlp` for transcript and person resolution, and to the
  platform clipboard tool (`pbpaste`, `wl-paste`, `xclip`, `xsel`, `Get-Clipboard`).
  All of these run with a timeout and are skipped when the binary is absent.
- **Network calls** go only to the model backend you configured — a local Ollama, or
  Anthropic/OpenAI if you opted into the `[api]` extra. Capture, ingest, and person
  resolution work with no model and no API key at all.
- **Everything else is your filesystem.** ugraph writes plain Markdown into the
  knowledge base directory you point it at, and nowhere else.
