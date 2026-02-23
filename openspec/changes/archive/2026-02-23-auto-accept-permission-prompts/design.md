## Context

Claude Code agents in the orchestrator pipeline occasionally encounter permission prompts ("Would you like to run the following command?") even when launched with `--dangerously-skip-permissions`. This happens for operations outside the sandbox (e.g., spawning subprocesses). The Claude Code provider's `get_status()` does not recognize these prompts — they fall through all pattern checks and return `PROCESSING`. The orchestrator then waits indefinitely (up to 30 min timeout) while the agent is blocked on user input.

Q CLI and Kiro CLI providers already detect permission prompts via `_permission_prompt_pattern` and return `WAITING_USER_ANSWER`. The orchestrator loop currently treats `WAITING_USER_ANSWER` only as a startup indicator (`agent_started = True`) but takes no action to resolve it.

## Goals / Non-Goals

**Goals:**
- Detect Claude Code permission prompts in `get_status()` and return `WAITING_USER_ANSWER`
- Provide opt-in auto-accept (`AUTO_ACCEPT_PERMISSIONS=1` env var, default off)
- Prevent spam with cooldown timer (5s) and safety cap (20 per turn)
- Audit-log every auto-accept with terminal output snippet for traceability
- Maintain test coverage for both provider detection and orchestrator handling

**Non-Goals:**
- Detecting every possible interactive prompt (focused on known Claude Code permission patterns)
- Changing Q CLI or Kiro CLI providers (they already work correctly)
- Command-class allowlisting (all permission prompts are treated equally when auto-accept is on)

## Decisions

### 1. Permission pattern list with fallbacks
**Rationale**: A single pattern is brittle against wording changes. Use an ordered list of patterns checked against ANSI-stripped `tail_output` (last 15 lines):
```python
PERMISSION_PROMPT_PATTERNS = [
    r"Would you like to run",           # Primary: command/MCP tool prompts
    r"Do you want to .* outside",       # Sandbox escape confirmation
    r"Allow .* to run",                 # Generic allow phrasing
]
```
Match succeeds if ANY pattern hits. ANSI codes are already stripped by `get_status()` before pattern matching (line 191). Stale detection: if an `IDLE_PROMPT_PATTERN` (`^[>❯]\s`) appears after the last match, the prompt was answered.

**Alternative considered**: Single `r"Would you like to run"` — rejected because minor wording changes would reintroduce the stall.

### 2. Opt-in via `AUTO_ACCEPT_PERMISSIONS` env var (default off)
**Rationale**: Auto-accepting creates a permission boundary change. Making it opt-in ensures existing users are not silently affected. When off, the orchestrator detects the prompt and logs a warning but does not send `y` — the pipeline will eventually hit idle grace / timeout, which is the current (broken) behavior. Users who want autonomous operation set `AUTO_ACCEPT_PERMISSIONS=1`.

**Alternative considered**: Always-on (rejected — safety regression per review finding #1), command-class allowlisting (rejected — over-engineering for the current use case, can be added later).

### 3. Stale detection: check for idle prompt after permission text
**Rationale**: If an `IDLE_PROMPT_PATTERN` (`^[>❯]\s`) appears after the last permission prompt match, the prompt was already answered and is stale. This differs from Q CLI/Kiro CLI which count idle lines — Claude Code's UI doesn't re-render the agent prompt line after answering a permission dialog the same way.

### 4. Auto-accept in `wait_for_response_file()` with `api.send_input(terminal_id, "y")`
**Rationale**: Using the existing `api.send_input()` keeps the approach uniform with how reminders are sent. The `y` response accepts Claude Code's permission dialog.

### 5. Cooldown (5s) + safety cap (20 per turn) + audit log
**Rationale**: Cooldown prevents rapid-fire `y` sends if the provider status oscillates. The cap (20) is high enough for legitimate multi-permission turns but catches infinite loops. Cap resets at each `send_and_wait()` call (i.e., per agent turn). Every auto-accept logs: role, terminal ID, accept count, and a 5-line terminal tail snippet so the operator can audit what was approved.

## Risks / Trade-offs

- **False positive on permission text in agent output** → Mitigated by checking only `tail_output` (15 lines), requiring no idle prompt after the match, and multiple patterns narrowing the scope.
- **`send_input("y")` not accepted by Claude Code** → `send_input` uses tmux paste-buffer. If Claude Code needs a raw keypress, a lower-level tmux `send-keys` would be needed. Integration testing will validate.
- **Permission prompt format changes in future Claude Code versions** → Pattern list is extensible. New patterns can be added without structural changes.
- **Auto-accept approving unintended commands** → Mitigated by opt-in flag (off by default) and audit logging of every acceptance. Users explicitly opt in knowing the pipeline will approve all permission prompts.
