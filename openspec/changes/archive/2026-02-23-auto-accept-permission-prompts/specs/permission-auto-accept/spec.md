## ADDED Requirements

### Requirement: Claude Code provider detects permission prompts
The Claude Code provider `get_status()` SHALL check terminal tail output against an ordered list of permission prompt patterns. If any pattern matches and no idle prompt (`^[>❯]\s`) appears after the last match, `get_status()` SHALL return `TerminalStatus.WAITING_USER_ANSWER`.

The pattern list SHALL include at minimum:
- `r"Would you like to run"` (command and MCP tool prompts)
- `r"Do you want to .* outside"` (sandbox escape confirmation)
- `r"Allow .* to run"` (generic allow phrasing)

Pattern matching SHALL be performed on ANSI-stripped output.

#### Scenario: Active permission prompt detected
- **WHEN** the terminal tail output contains "Would you like to run the following command?" and no idle prompt (`^[>❯]\s`) appears after it
- **THEN** `get_status()` SHALL return `TerminalStatus.WAITING_USER_ANSWER`

#### Scenario: Sandbox escape prompt detected
- **WHEN** the terminal tail output contains "Do you want to run the frontend production build outside sandbox" and no idle prompt appears after it
- **THEN** `get_status()` SHALL return `TerminalStatus.WAITING_USER_ANSWER`

#### Scenario: Stale permission prompt ignored
- **WHEN** the terminal tail output contains "Would you like to run" but an idle prompt (`^[>❯]\s`) appears after it
- **THEN** `get_status()` SHALL NOT return `WAITING_USER_ANSWER` (the prompt was already answered)

#### Scenario: Spinner takes priority over permission text
- **WHEN** the terminal tail output contains both "Would you like to run" and an active spinner matching `PROCESSING_PATTERN`
- **THEN** `get_status()` SHALL return `TerminalStatus.PROCESSING` (spinner check runs first)

### Requirement: Orchestrator auto-accepts permission prompts when opted in
The orchestrator loop `wait_for_response_file()` SHALL auto-accept permission prompts by sending `y` via `api.send_input()` when ALL of the following conditions are met:
1. `api.get_status()` returns `waiting_user_answer`
2. The `AUTO_ACCEPT_PERMISSIONS` env var is set to `1` (default: `0` / off)
3. The cooldown period (5.0 seconds) has elapsed since the last auto-accept for this terminal
4. The per-turn accept count has not exceeded the safety cap (20)

When `AUTO_ACCEPT_PERMISSIONS` is not `1` and `waiting_user_answer` is detected, the orchestrator SHALL log a warning but SHALL NOT send `y`.

#### Scenario: Permission prompt auto-accepted (opt-in enabled)
- **WHEN** `AUTO_ACCEPT_PERMISSIONS=1` and `api.get_status()` returns `waiting_user_answer` and cooldown has elapsed and cap not exceeded
- **THEN** the orchestrator SHALL send `y` to the terminal via `api.send_input()`, log the event with terminal tail snippet, increment the per-turn counter, and continue polling

#### Scenario: Permission prompt detected but auto-accept disabled
- **WHEN** `AUTO_ACCEPT_PERMISSIONS` is not `1` and `api.get_status()` returns `waiting_user_answer`
- **THEN** the orchestrator SHALL log a warning including the role and terminal ID but SHALL NOT send `y`

#### Scenario: Cooldown prevents rapid accepts
- **WHEN** `AUTO_ACCEPT_PERMISSIONS=1` and `api.get_status()` returns `waiting_user_answer` and the last auto-accept for this terminal was sent less than 5.0 seconds ago
- **THEN** the orchestrator SHALL skip sending `y` and continue polling

#### Scenario: Safety cap exceeded
- **WHEN** `AUTO_ACCEPT_PERMISSIONS=1` and the number of auto-accepts for the current agent turn exceeds 20
- **THEN** the orchestrator SHALL raise `RuntimeError` with a message including the role, terminal ID, and cap value

### Requirement: Audit logging for every auto-accept
Every auto-accept event SHALL be logged via the orchestrator's `log()` function with:
- Agent role name
- Terminal ID
- Current accept count for this turn
- A snippet of the terminal tail output (up to 5 lines) showing what was accepted

#### Scenario: Audit log content
- **WHEN** an auto-accept is sent
- **THEN** the log message SHALL contain the role, terminal ID, accept count (e.g., "2/20"), and a multi-line terminal snippet

### Requirement: Permission accept counter resets per agent turn
The per-turn permission accept counter SHALL reset to zero at the start of each `send_and_wait()` call (i.e., when a new prompt is dispatched to the agent).

#### Scenario: Counter reset on new turn
- **WHEN** `send_and_wait()` is called for a new agent prompt
- **THEN** `_permission_accept_count` for that terminal SHALL be reset to `0`

## MODIFIED Requirements

### Requirement: Orchestrator polling recognizes waiting_user_answer
The existing `wait_for_response_file()` polling loop currently treats `waiting_user_answer` only as a startup indicator. It SHALL now additionally check for opt-in auto-accept handling as defined above, before the file-exists and idle-grace checks.

#### Scenario: waiting_user_answer no longer causes indefinite stall
- **WHEN** a terminal returns `waiting_user_answer` status during polling
- **THEN** the orchestrator SHALL either auto-accept (if opted in) or log a warning (if not), rather than silently treating it as processing
