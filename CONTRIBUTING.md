# Contributing

## Development setup

Hermetic Club targets Python 3.11+. Install the locked development environment
with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --locked --extra dev
```

## Verification

Run the same checks used by CI:

```bash
uv lock --check
uv run python -m compileall -q src tests
uv run pytest -q
```

Ruff is enforced on changed Python files in pull requests. Existing repository-
wide findings are tracked separately and should not be expanded by new work.

## Pull requests

- Use a focused branch and conventional commit message.
- Add regression tests for behavior changes and security fixes.
- Do not include credentials, local databases, or generated build artifacts.
- Describe known baseline failures separately from failures introduced by the PR.
- Keep security-sensitive changes small enough for independent review.

## Operational changes

Changes affecting enrollment, authentication, webhooks, database persistence,
or agent-to-agent visibility require explicit authorization tests and a
read-only or isolated integration test before merging.
