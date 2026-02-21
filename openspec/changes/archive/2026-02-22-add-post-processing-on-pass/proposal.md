## Why

When the orchestrator reaches FINAL: PASS, it immediately exits without performing any housekeeping. The user must manually run OpenSpec archive and git commit after every successful run. When OpenSpec is used in a run (e.g., the analyst creates/updates artifacts), these post-processing steps can be automated as an opt-in convenience.

## What Changes

- Add a `post_processing` section to the JSON config with `openspec_archive` (bool, default false) and `git_commit` (bool, default false) options
- When enabled, add orchestrator-driven post-processing logic that runs after FINAL: PASS and before cleanup/exit
- When all post-processing options are disabled (default), the PASS branch behaves exactly as today
- Post-processing steps when enabled (in order):
  1. **OpenSpec archive** (`openspec_archive: true`):
     - Detect the active change: list non-archived directories under `openspec/changes/`, excluding `archive/`
     - If exactly one active change exists, use it; if zero or multiple, skip with a log warning (no error, no guess)
     - Run `openspec archive <name> --yes` (non-interactive) which handles spec sync + directory move internally
     - If archive fails, log the error and skip the git commit step
  2. **Git commit** (`git_commit: true`):
     - Only runs if the working directory is a git repo
     - Only runs if the OpenSpec archive step succeeded (when both are enabled) or was not requested
     - Run `git add -A` in the working directory
     - Check `git diff --cached --quiet`; if no staged changes, skip commit with a log message (no empty commits)
     - Run `git commit -m "<standard message>"`
     - If git commit fails (e.g., missing identity, hook failure), log the error and continue to exit
- Each step logs its result (success/skip/fail) but never blocks exit
- Add env var overrides: `POST_OPENSPEC_ARCHIVE`, `POST_GIT_COMMIT`

## Capabilities

### New Capabilities
- `post-processing`: Opt-in orchestrator-driven post-processing after FINAL: PASS (OpenSpec archive + git commit)

### Modified Capabilities
- `json-config`: Add `post_processing` section to JSON config structure
- `python-orchestrator`: Add post-processing execution between FINAL: PASS and cleanup/exit

## Impact

- `examples/agnostic-3agents/run_orchestrator_loop.py` — add post-processing functions and call them from the PASS branch
- `examples/agnostic-3agents/config-*.json` — add `post_processing` section to sample configs
- `openspec/specs/json-config/spec.md` — document new config keys
- `openspec/specs/python-orchestrator/spec.md` — document post-processing behavior
- `test/examples/test_orchestrator_loop_unit.py` — add tests for post-processing logic
