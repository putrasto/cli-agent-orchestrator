# AGENTS.md

This file defines practical working rules for coding agents in this repository.

## Scope

- Applies to the whole repository.
- If a subdirectory contains another `AGENTS.md`, the closer file takes precedence for that subtree.

## Environment

- Python: `3.10+`
- Package manager and runner: `uv`
- Default setup command:

```bash
uv sync
```

## Canonical Commands

- Run all tests:

```bash
uv run pytest -v
```

- Run a focused unit test file:

```bash
uv run pytest test/examples/test_orchestrator_loop_unit.py -q
```

- Format code:

```bash
uv run black src/ test/
uv run isort src/ test/
```

- Type check:

```bash
uv run mypy src/
```

## Preferred Validation Order

1. Run targeted tests for changed files.
2. Run `uv run pytest -v` if changes are broad or cross-cutting.
3. Run formatting and type checks before finalizing.

## OpenSpec Workflow

- OpenSpec change artifacts live under `openspec/changes/<change-name>/`.
- When implementing or reviewing a change, keep `proposal.md`, `design.md`, `tasks.md`, and delta specs in sync with code.
- If behavior changes, update specs in the same change.

## Agent Safety Rules

- Avoid destructive commands unless explicitly requested.
- Do not delete tests to make failures pass.
- Prefer minimal, targeted edits.
- Keep temporary artifacts in `.tmp/` or `/tmp/`.

## Notes for Orchestrator Example

- For `examples/agnostic-3agents/run_orchestrator_loop.py`, use file-based response handoff.
- If strict file-only handoff is required, set:

```bash
STRICT_FILE_HANDOFF=1
```

- Recommended test command for this area:

```bash
uv run pytest -q test/examples/test_orchestrator_loop_unit.py
```
