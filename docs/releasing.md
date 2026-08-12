# Releasing ugraph-kit

The Python distribution is `ugraph-kit`; the installed executable is `ugraph`.
PyPI's bare `ugraph` name belongs to an unrelated project.

## One-time setup

1. Put this project in its own GitHub repository. The workflow files must be at
   `.github/workflows/` in that repository.
2. Create a PyPI account and enable two-factor authentication.
3. On PyPI, add a **Trusted Publisher** for:
   - owner: the GitHub account or organization
   - repository: the ugraph repository name
   - workflow: `publish.yml`
   - environment: `pypi`
4. In the GitHub repository, create an environment named `pypi`. Optionally add
   required reviewers so releases cannot publish accidentally.

No long-lived PyPI API token is needed.

## Release

1. Update the version in both `pyproject.toml` and
   `src/ugraph/__init__.py`.
2. Run:

   ```bash
   uv run pytest
   uv build
   uvx twine check dist/*
   ```

3. Commit and push the version change.
4. Create a GitHub release tagged with the same version, for example `v0.1.0`.

Publishing the GitHub release triggers `publish.yml`. PyPI rejects an existing
version, so every release needs a new version number.

## Local install check

Test the wheel rather than the editable source tree:

```bash
uv venv --python 3.11 .smoke
uv pip install --python .smoke/bin/python dist/*.whl
.smoke/bin/ugraph --version
.smoke/bin/ugraph person --help
```
