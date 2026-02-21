## Context

The orchestrator's PASS branch currently calls `save_state()`, logs "FINAL: PASS", runs `cleanup()`, and exits. There is no hook for post-run housekeeping. Users who use OpenSpec in their pipeline must manually run `openspec archive` and `git commit` after every successful run.

The orchestrator already has a config table pattern (`_CONFIG_KEYS`) that maps dotted JSON keys to flat Python globals, with env var overrides and type coercion. New config keys follow this pattern.

## Goals / Non-Goals

**Goals:**
- Add opt-in post-processing that runs after FINAL: PASS, before cleanup/exit
- Support two independent steps: OpenSpec archive and git commit
- Follow existing config patterns (JSON section + env var overrides + defaults)
- Make post-processing failures non-fatal (log and continue to exit)

**Non-Goals:**
- Running post-processing on FAIL (only on PASS)
- Full OpenSpec verify (agent-driven codebase analysis) — the tester already verified correctness
- Supporting arbitrary post-processing hooks or plugins
- Pushing to remote (commit only, no push)

## Decisions

### Decision: Orchestrator-driven, not agent-driven
Post-processing runs as Python subprocess calls in the orchestrator, not as prompts sent to an agent terminal.

**Rationale:** All steps are mechanical (CLI commands, file operations, git commands). Agent-driven execution adds tmux overhead, can deviate or hallucinate, and risks getting stuck. The orchestrator can call `openspec archive` and `git commit` directly via `subprocess.run()`.

**Alternative considered:** Sending a post-processing prompt to the analyst agent. Rejected because it introduces unreliability for deterministic operations.

### Decision: Use `openspec archive <name> --yes` for non-interactive execution
The `openspec archive` CLI command may prompt for confirmation. The `--yes` flag bypasses prompts for automation.

**Rationale:** The orchestrator runs unattended after FINAL: PASS. Interactive prompts would block indefinitely.

### Decision: Exactly-one active change detection
Scan `openspec/changes/` for non-`archive` subdirectories. If exactly one exists, use it. If zero or multiple, skip with a log warning.

**Rationale:** Guessing which change to archive when multiple exist is unsafe. Zero changes means OpenSpec wasn't used in this run. Both cases should skip gracefully rather than error.

### Decision: Git commit gated on archive success
When both `openspec_archive` and `git_commit` are enabled, git commit only runs if archive succeeded or was skipped (no active change). If archive failed, git commit is skipped.

**Rationale:** Committing after a failed archive would capture an inconsistent state. If only `git_commit` is enabled (without `openspec_archive`), the gate doesn't apply.

### Decision: Run in working directory, not orchestrator directory
Both `openspec archive` and `git` commands run with `cwd=WD` (the project working directory), not the orchestrator's own directory.

**Rationale:** The OpenSpec changes and git repo belong to the project being worked on, not the orchestrator tool.

## Risks / Trade-offs

- **`openspec archive --yes` may not exist yet** → Verify the flag exists; if not, implement without it and document the limitation. The `--yes` flag is common in CLI tools and likely supported.
- **Race condition with cleanup** → Post-processing runs before `cleanup()`, so terminals are still alive. This is intentional — terminals are only cleaned up after post-processing completes.
- **Git add -A captures unintended files** → The project's `.gitignore` is the safety net. The orchestrator doesn't curate which files to stage. This matches normal development workflow.
