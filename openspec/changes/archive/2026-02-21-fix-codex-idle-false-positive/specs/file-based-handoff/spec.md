## MODIFIED Requirements

### Requirement: Poll for response file with terminal status gate
The system SHALL poll for the response file with the following logic:
1. If terminal status is `error`, raise an error immediately
2. If the response file exists AND terminal status is `idle` or `completed`, read the file, archive it, and return its content
3. If terminal is `idle`/`completed` without response file for `IDLE_GRACE_SECONDS`:
   - When `STRICT_FILE_HANDOFF` is True (default): raise a `RuntimeError` (no fallback)
   - When `STRICT_FILE_HANDOFF` is False: fall back to `api.get_last_output()`
4. If timeout is exceeded AND terminal is still `processing`, raise a `TimeoutError`

The Codex provider's terminal status detection SHALL use only Codex-specific UI patterns (`ACTIVE_WORK_UI_PATTERN`) — not generic English keyword matches (`PROCESSING_PATTERN`) — to override idle detection. Generic keywords like "running", "working", "executing" in agent narrative text SHALL NOT prevent idle or completed status from being reported.

The `ACTIVE_WORK_UI_PATTERN` SHALL anchor `Exploring` to the Codex bullet prefix (`•\s+Exploring\b`) to prevent narrative text containing the word "exploring" from causing false-processing detection.

The Codex provider's `USER_PREFIX_PATTERN` SHALL only match horizontal whitespace (spaces and tabs) between the `›` prompt character and user input text, preventing cross-line false matches.

#### Scenario: Agent writes response file and terminal becomes idle
- **WHEN** the agent writes to the response file and terminal status is `idle`
- **THEN** the orchestrator SHALL read the file content, archive the file, and return the content

#### Scenario: Agent ignores file instruction but terminal finishes (default mode)
- **WHEN** the timeout expires, no response file exists, terminal status is `idle`, and `STRICT_FILE_HANDOFF` is False
- **THEN** the orchestrator SHALL fall back to `api.get_last_output()` and return that output

#### Scenario: Agent ignores file instruction but terminal finishes (strict mode)
- **WHEN** the timeout expires, no response file exists, terminal status is `idle`, and `STRICT_FILE_HANDOFF` is True
- **THEN** the orchestrator SHALL raise a `RuntimeError` without falling back to terminal output

#### Scenario: Terminal enters error state
- **WHEN** the terminal status becomes `error` during polling
- **THEN** the orchestrator SHALL raise a `RuntimeError`

#### Scenario: Timeout with terminal still processing
- **WHEN** the timeout expires and terminal status is `processing`
- **THEN** the orchestrator SHALL raise a `TimeoutError`

#### Scenario: Narrative keyword does not block idle detection
- **WHEN** Codex agent output contains the word "running" in narrative text (e.g., "stop running commands") AND the terminal shows a valid idle prompt with context footer
- **THEN** the provider SHALL report status as `idle` or `completed`, not `processing`

#### Scenario: Active work UI correctly blocks idle detection
- **WHEN** Codex agent output contains "esc to interrupt" or "• Exploring" AND the terminal shows idle prompt signals from a previous turn
- **THEN** the provider SHALL report status as `processing`

#### Scenario: Narrative "exploring" does not block idle detection
- **WHEN** Codex agent output contains "I was exploring the codebase" in narrative text (without bullet prefix) AND the terminal shows a valid idle prompt with context footer
- **THEN** the provider SHALL report status as `idle` or `completed`, not `processing`

#### Scenario: USER_PREFIX_PATTERN does not match across newlines
- **WHEN** terminal output contains a standalone `›` on its own line followed by a newline and `100% context left`
- **THEN** the `›\n100%...` SHALL NOT match `USER_PREFIX_PATTERN`
- **AND** a `›` followed by horizontal whitespace and text on the same line (e.g., `› Reply with READY`) SHALL match

#### Scenario: Standalone chevron prompt not misdetected as user input
- **WHEN** Codex terminal output ends with `›\n100% context left\n` (standalone `›` on its own line)
- **THEN** the `›` line SHALL NOT be treated as a user input line
- **AND** if an assistant response preceded the `›` prompt, the status SHALL be `completed`

#### Scenario: Standalone chevron with prior assistant produces completed
- **WHEN** terminal output contains a user prompt, then assistant response, then standalone `›\n` followed by context footer
- **THEN** the provider SHALL report status as `completed` (not `idle`)
