# Agent contribution guide

## Repository context

Hermetic Club is a Python 3.11+ FastAPI application with an async SQLite
backend, Jinja2/htmx UI, agent API, CLI, and optional integrations. The source
skill is `hermes-skill/`; harness-specific copies live under `.codex/skills/`,
`.omp/skills/`, `.opencode/skills/`, `.claude/skills/`, and `.hermes/skills/`.

Never assume a checkout path. Discover it with `git rev-parse --show-toplevel`.
Never commit API keys, local databases, generated build output, or machine-
specific agent-home paths.

## Agent skill changes

Keep `hermes-skill/SKILL.md` as the shared contract and update every tracked
harness adapter when behavior or safety rules change. Adapters must use their
host harness primitives, remain standalone, and preserve the same API, budget,
draft, cooldown, handoff, and untrusted-content rules. Installed Hermes copies
are copies, not symlinks.

## Development and verification

```bash
uv sync --locked --extra dev
uv run python -m compileall -q src tests
uv run pytest -q
uv run ruff check src tests hermes-skill
uv run python -m build
```

Run focused tests while iterating, then run the full suite. Report pre-existing
failures separately from regressions introduced by the change. Use `git diff
--check` before committing.

## Review and publication

Use a focused side branch based on the current `origin/main`. Preserve unrelated
work. Perform a local independent review/fix loop before committing. Before
pushing, verify `gh auth status` and repository write permission. Open the PR as
a draft, wait for checks for the exact head SHA, fix failures, and obtain a fresh
independent review after every pushed fix. Convert to ready only when CI is green
and no merge blockers remain; leave merging to the user.
