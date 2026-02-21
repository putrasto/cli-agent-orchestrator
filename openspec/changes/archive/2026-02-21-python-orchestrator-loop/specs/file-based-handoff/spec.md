## ADDED Requirements

### Requirement: Response file path mapping
The system SHALL map each agent role to a unique response file path under `.tmp/agent-responses/`:
- `analyst` → `analyst_summary.md`
- `analyst_review` → `analyst_review.md`
- `programmer` → `programmer_summary.md`
- `programmer_review` → `programmer_review.md`
- `tester` → `test_result.md`

#### Scenario: Each role resolves to the correct file
- **WHEN** `response_path_for(role)` is called for each of the 5 roles
- **THEN** the returned path SHALL be `RESPONSE_DIR / <filename>` matching the mapping above

### Requirement: Stale response file cleanup
The system SHALL delete any existing response file for a role before sending a new prompt to that agent.

#### Scenario: Stale file from previous run exists
- **WHEN** `clear_stale_response("analyst")` is called and `analyst_summary.md` exists
- **THEN** the file SHALL be deleted

#### Scenario: No stale file exists
- **WHEN** `clear_stale_response("analyst")` is called and no file exists
- **THEN** no error SHALL be raised

### Requirement: Response directory creation
The system SHALL create the `.tmp/agent-responses/` directory (including parents) if it does not exist.

#### Scenario: Directory does not exist
- **WHEN** `ensure_response_dir()` is called and the directory is missing
- **THEN** the directory SHALL be created with all parent directories

### Requirement: Poll for response file with terminal status gate
The system SHALL poll for the response file with the following logic:
1. If terminal status is `error`, raise an error immediately
2. If the response file exists AND terminal status is `idle` or `completed`, read the file, delete it, and return its content
3. If timeout is exceeded AND terminal is `idle`/`completed`:
   - When `STRICT_FILE_HANDOFF` is True (default): raise a `RuntimeError` (no fallback)
   - When `STRICT_FILE_HANDOFF` is False: fall back to `api.get_last_output()`
4. If timeout is exceeded AND terminal is still `processing`, raise a `TimeoutError`

#### Scenario: Agent writes response file and terminal becomes idle
- **WHEN** the agent writes to the response file and terminal status is `idle`
- **THEN** the orchestrator SHALL read the file content, delete the file, and return the content

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

### Requirement: Response file instruction injection
Each agent prompt SHALL have a `RESPONSE FILE INSTRUCTION` block appended that tells the agent to write its complete final response to the role's response file path using a heredoc shell command.

#### Scenario: Analyst prompt includes file instruction
- **WHEN** the analyst prompt is built
- **THEN** it SHALL contain the absolute path to `analyst_summary.md` inside a `RESPONSE FILE INSTRUCTION` block

#### Scenario: All five agent roles have file instructions
- **WHEN** prompts are built for all 5 roles
- **THEN** each SHALL contain the correct response file path for that role

### Requirement: Send-and-wait convenience function
`send_and_wait(terminal_id, role, message)` SHALL clear the stale response file, send the message via the API, and wait for the response file, returning the response content.

#### Scenario: Normal send-and-wait flow
- **WHEN** `send_and_wait()` is called
- **THEN** it SHALL call `clear_stale_response()`, then `api.send_input()`, then `wait_for_response_file()`, and return the result
