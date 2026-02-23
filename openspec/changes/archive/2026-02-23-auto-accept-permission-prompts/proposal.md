## Why

When Claude Code agents encounter permission prompts ("Would you like to run the following command?"), the orchestrator pipeline gets stuck indefinitely. The Claude Code provider misclassifies the permission dialog as `PROCESSING` (falls through all pattern checks), so the orchestrator keeps polling for up to 30 minutes without intervening. Q CLI and Kiro CLI already handle permission prompts correctly — Claude Code needs the same treatment.

## What Changes

- Add permission prompt detection to the Claude Code provider (`get_status()` returns `WAITING_USER_ANSWER` when a permission dialog is active), using a list of patterns with fallbacks to handle wording variations
- Add opt-in auto-accept logic in the orchestrator loop (`AUTO_ACCEPT_PERMISSIONS=1` env var, default off) — when `waiting_user_answer` is detected, send `y` to auto-accept with a 5-second cooldown and 20-per-turn safety cap
- Audit-log every auto-accept event with a terminal output snippet for traceability
- Add unit tests for both the provider detection and orchestrator auto-accept behavior

## Capabilities

### New Capabilities
- `permission-auto-accept`: Detect Claude Code permission prompts and optionally auto-accept them in the orchestrator loop to prevent pipeline stalls

### Modified Capabilities
- `python-orchestrator`: The orchestrator polling loop gains `waiting_user_answer` handling with opt-in auto-accept, cooldown, safety cap, and audit logging

## Impact

- `src/cli_agent_orchestrator/providers/claude_code.py` — new pattern list + detection logic in `get_status()`
- `examples/agnostic-3agents/run_orchestrator_loop.py` — auto-accept handling in `wait_for_response_file()`, rate-limiting state, reset in `send_and_wait()`, `AUTO_ACCEPT_PERMISSIONS` env var
- `test/providers/test_claude_code_provider_unit.py` — new test cases for permission prompt detection
- `test/examples/test_orchestrator_loop_unit.py` — new test class for auto-accept behavior
