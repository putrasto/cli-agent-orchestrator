## Why

After dispatching a prompt to a CLI agent, the orchestrator's idle grace timer starts immediately because the terminal still shows the OLD idle/completed state from the previous turn. If the agent takes longer than `IDLE_GRACE_SECONDS` (30s) to complete, it is falsely declared "done" — triggering a fatal error under `STRICT_FILE_HANDOFF=1`. This was observed in production: a programmer agent (claude_code) was killed after 31 seconds even though it was actively processing.

## What Changes

- Add an `agent_started` guard to `wait_for_response_file()` that prevents the idle grace timer from starting until the agent has been observed in a non-idle/completed state (PROCESSING, WAITING_USER_ANSWER, etc.) at least once
- Add a startup timeout fallback: if the agent never enters a non-idle state within `IDLE_GRACE_SECONDS`, force-release the guard with a warning log and begin normal grace timing
- No new config keys, API methods, or imports required
- Update existing grace-related tests to include a PROCESSING observation before idle/completed sequences

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `file-based-handoff`: The idle grace timer behavior changes — it no longer starts on the first poll after dispatch. A startup guard delays grace timing until the agent has demonstrably started processing.

## Impact

- `examples/agnostic-3agents/run_orchestrator_loop.py` — `wait_for_response_file()` modified (~15 lines)
- `test/examples/test_orchestrator_loop_unit.py` — 6 new tests, 2 existing tests updated
- `openspec/specs/file-based-handoff/spec.md` — updated via delta spec
- `examples/agnostic-3agents/README.md` — `IDLE_GRACE_SECONDS` description updated
