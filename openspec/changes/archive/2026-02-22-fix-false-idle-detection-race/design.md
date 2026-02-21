## Context

The orchestrator loop dispatches prompts via `send_and_wait()` → `api.send_input()` → `wait_for_response_file()`. The polling loop in `wait_for_response_file()` checks terminal status every `POLL_SECONDS` (default 2s). When status is idle/completed without a response file, an `idle_since` timer starts. After `IDLE_GRACE_SECONDS` (default 30s) of continuous idle/completed, the agent is declared done.

The race condition: after `send_input()` delivers text via tmux, the CLI agent hasn't read it yet (0.3-2s latency). The status checker sees the OLD idle prompt from the previous turn and starts the grace timer immediately. If the agent takes >30s to complete, it's falsely killed.

## Goals / Non-Goals

**Goals:**
- Prevent idle grace timer from starting before the agent has demonstrably begun processing
- Zero additional API calls or token consumption — use only the existing `get_status()` poll
- Maintain backward compatibility — agents that show PROCESSING before idle continue to work identically

**Non-Goals:**
- Redesigning provider status detection (out of scope)
- Adding new config keys or API surface
- Solving spinner-flicker during active processing (already handled by existing `idle_since = None` reset on each PROCESSING poll)

## Decisions

### D1: Guard idle grace with `agent_started` flag

Add `agent_started = False` to `wait_for_response_file()`. The idle grace timer only starts counting after `agent_started` is True. The flag is set when `status not in ("idle", "completed")` — covering PROCESSING, WAITING_USER_ANSWER, and any future non-terminal status values.

**Alternative considered**: Pre-dispatch output hash comparison. Rejected because it requires a new `get_output()` API method, adds I/O overhead on every poll (hashing 200+ lines every 2s), and the startup timeout fallback already covers the edge case.

**Alternative considered**: Fixed sleep after `send_input()`. Rejected because it wastes time on every dispatch and only shifts the race window without eliminating it.

### D2: Startup timeout reuses `IDLE_GRACE_SECONDS`

If the agent never shows a non-idle status within `IDLE_GRACE_SECONDS` (30s), the guard is force-released with a warning log and grace timing begins normally. Worst-case total wait before false-positive = 2 × `IDLE_GRACE_SECONDS` = 60s (30s startup + 30s grace).

**Alternative considered**: Separate `STARTUP_TIMEOUT` config key. Rejected — YAGNI, and 30s is a reasonable startup window for all current providers.

### D3: No changes to `send_and_wait()` signature

The fix is entirely within `wait_for_response_file()`. No new parameters, no changes to the caller. This keeps the blast radius minimal.

## Risks / Trade-offs

- **[Risk] Agent never enters PROCESSING state** → Startup timeout fallback handles this. Total wait increases from 30s to 60s before false-positive fires. Acceptable trade-off vs the current 100% false-positive in the startup race.

- **[Risk] Existing tests assume immediate grace start** → Two existing tests (`test_fallback_on_idle_grace_expired`, `test_strict_handoff_raises_on_idle_grace`) need mock sequences updated to include a PROCESSING status before idle, so `agent_started` is True.

- **[Trade-off] Worst-case 60s wait vs current 30s** → The 30s was too short (caused the bug). 60s is still well within the 1800s RESPONSE_TIMEOUT.
