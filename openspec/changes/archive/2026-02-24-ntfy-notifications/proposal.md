## Why

The orchestrator pipeline can run for extended periods (up to 30+ minutes per round, multiple rounds). Operators need mobile notifications for key events — pipeline completion (PASS/FAIL), agents stuck on unrecognized prompts, errors, and timeouts — so they can step away without risking unnoticed stalls.

## What Changes

- Add a `notify()` helper function that POSTs to `ntfy.sh/<topic>` with title, message, and priority
- Add `NTFY_TOPIC` config key (env var + JSON config path `notifications.ntfy_topic`) — when unset, notifications are silently skipped
- Add `"notifications"` to `VALID_TOP_LEVEL_KEYS` so JSON configs with this section pass validation
- Call `notify()` at key orchestrator events: PASS, FAIL, terminal error, response timeout, stuck agent (waiting_user_answer with auto-accept off, rate-limited to once per role per turn)
- Add unit tests for the notify helper, config validation, and integration points

## Capabilities

### New Capabilities
- `ntfy-notifications`: Push notifications via ntfy.sh for pipeline events (completion, errors, stuck agents)

### Modified Capabilities
- `json-config`: Add `"notifications"` to `VALID_TOP_LEVEL_KEYS` so the new config section is accepted

## Impact

- `examples/agnostic-3agents/run_orchestrator_loop.py` — new `notify()` function, new config key, `VALID_TOP_LEVEL_KEYS` update, notification calls at event points
- `test/examples/test_orchestrator_loop_unit.py` — tests for notify helper, config validation, and event triggers
