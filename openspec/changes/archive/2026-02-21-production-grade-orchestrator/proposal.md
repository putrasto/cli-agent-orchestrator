## Why

The orchestrator loop currently relies on 24 environment variables for configuration, which is error-prone (missing `\` breaks the shell command), hard to version-control, and forces all 5 agents to use the same AI provider. Moving to a JSON config file enables per-agent provider selection, repeatable invocations, and scenario-specific config presets. Additionally, the analyst prompt on retry rounds does not leverage the explore skill before fast-forward, producing weaker root cause analysis, terminal names in tmux are opaque IDs that make debugging difficult, and the run always starts from analyst even when operators want to jump directly to later stages.

## What Changes

- **JSON config file** as the primary configuration mechanism. A single `config.json` replaces 25 env vars (existing 24 + new `START_AGENT`). Config precedence (highest to lowest): env vars → JSON file → hardcoded defaults. Env vars always win over JSON — this supports CI/automation overrides. Env vars map to the same flat keys as today plus the new start option: `API`, `PROVIDER`, `WD`, `PROMPT`, `PROMPT_FILE`, `MAX_ROUNDS`, `POLL_SECONDS`, `MAX_REVIEW_CYCLES`, `PROJECT_TEST_CMD`, `MIN_REVIEW_CYCLES_BEFORE_APPROVAL`, `REQUIRE_REVIEW_EVIDENCE`, `REVIEW_EVIDENCE_MIN_MATCH`, `RESUME`, `CONDENSE_EXPLORE_ON_REPEAT`, `CONDENSE_REVIEW_FEEDBACK`, `MAX_FEEDBACK_LINES`, `CONDENSE_UPSTREAM_ON_REPEAT`, `CONDENSE_CROSS_PHASE`, `MAX_CROSS_PHASE_LINES`, `STATE_FILE`, `CLEANUP_ON_EXIT`, `RESPONSE_TIMEOUT`, `STRICT_FILE_HANDOFF`, `IDLE_GRACE_SECONDS`, `START_AGENT`. There are no `AGENTS_*` env vars — per-agent provider/profile is JSON-only.
- **Per-agent provider** — each of the 5 agents can use a different AI provider (e.g., analyst on `claude_code`, peer on `codex`). Validation is strict fail-fast: at startup, the orchestrator validates that every agent's provider is one of `codex`, `claude_code`, `q_cli`, `kiro_cli`. If a provider is invalid or the CAO server returns an error during terminal creation, the orchestrator cleans up all already-created terminals (calls `exit_terminal` for each), then exits with a clear error message. No fallback to a different provider.
- **Explore-before-ff on retry** — when the analyst receives FAIL feedback from the tester (round > 1), the prompt instructs it to run the OpenSpec explore skill first to investigate the failure, then the fast-forward skill to update artifacts. This applies to all retry rounds unconditionally — the explore step is always beneficial for root cause analysis regardless of failure type. No token budget guard; the agent's own context window is the natural limit.
- **Terminal rename after creation** — after each terminal is created, the orchestrator sends a rename command (e.g., `analyst-da33cf00`) so tmux windows are human-readable. Best-effort only: rename failure is logged as a warning and ignored. The orchestrator waits up to 5 seconds for the terminal to return to idle after rename; if it doesn't, it proceeds anyway. Rename is attempted for all providers — if the provider doesn't understand the command, it will be ignored or produce a benign error that the orchestrator skips.
- **Default agent config** — each role has a default provider and profile. If `agents` is omitted entirely, all 5 roles use the defaults. If `agents.<role>` is present but `profile` is omitted, the default profile for that role is used. If `agents.<role>` is present but `provider` is omitted, the top-level `provider` default is used. Unknown role names in the `agents` section cause a fatal error at startup — this catches config typos like `peer_anlyst` that would silently degrade behavior. The 5 recognized roles are: `analyst`, `peer_analyst`, `programmer`, `peer_programmer`, `tester`.
- **Start agent option** — a new `start_agent` option (or `START_AGENT` env var) controls the first dispatched agent for fresh runs. Allowed values are `analyst`, `peer_analyst`, `programmer`, `peer_programmer`, `tester`; default is `analyst`. The selected role is always dispatched first (including peer roles). To preserve this behavior, one-time missing-upstream fallback checks are bypassed on that first dispatch only; if upstream content is unavailable, prompts include explicit placeholder text and normal fallback logic resumes after the first dispatch. In resume mode, stored `current_phase` remains authoritative and `start_agent` is ignored.

### Default agent mapping

| Role | Default provider | Default profile |
|------|-----------------|-----------------|
| `analyst` | (top-level default) | `system_analyst` |
| `peer_analyst` | (top-level default) | `peer_system_analyst` |
| `programmer` | (top-level default) | `programmer` |
| `peer_programmer` | (top-level default) | `peer_programmer` |
| `tester` | (top-level default) | `tester` |

## Capabilities

### New Capabilities
- `json-config`: JSON file-based configuration with nested structure (agents, limits, condensation, handoff), strict env-over-JSON precedence, and sample configs for fresh/incremental/resume scenarios.

### Modified Capabilities
- `python-orchestrator`: Per-agent provider in ApiClient (provider passed per-call, not global), explore-before-ff analyst prompt on retry rounds, terminal rename after creation (best-effort), start-agent selection for fresh runs, config loading from JSON with env var override.

## Impact

- `examples/agnostic-3agents/run_orchestrator_loop.py` — config loading, start-agent role selection (first-dispatch role), ApiClient per-provider params, init_new_run rename step, build_analyst_prompt retry logic
- `examples/agnostic-3agents/*.json` — new sample config files (fresh, incremental, resume)
- `test/examples/test_orchestrator_loop_unit.py` — new tests for JSON loading, start-agent selection, per-agent provider, explore-before-ff prompt, rename calls
- No changes to CAO server code — all features use existing API capabilities
