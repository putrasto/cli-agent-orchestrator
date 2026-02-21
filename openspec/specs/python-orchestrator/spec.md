## ADDED Requirements

### Requirement: Configuration via environment variables
The orchestrator SHALL read all configuration from environment variables with the same names and defaults as the shell script, including: `API`, `PROVIDER`, `WD`, `PROMPT`, `PROMPT_FILE`, `MAX_ROUNDS`, `POLL_SECONDS`, `MAX_REVIEW_CYCLES`, `PROJECT_TEST_CMD`, `MIN_REVIEW_CYCLES_BEFORE_APPROVAL`, `REQUIRE_REVIEW_EVIDENCE`, `REVIEW_EVIDENCE_MIN_MATCH`, `RESUME`, `CONDENSE_EXPLORE_ON_REPEAT`, `CONDENSE_REVIEW_FEEDBACK`, `MAX_FEEDBACK_LINES`, `CONDENSE_UPSTREAM_ON_REPEAT`, `STATE_FILE`, `CLEANUP_ON_EXIT`. Additional: `RESPONSE_TIMEOUT` (default 1800), `STRICT_FILE_HANDOFF` (default 1, when 0 enables get_last_output fallback), `CONDENSE_CROSS_PHASE` (default 1), `MAX_CROSS_PHASE_LINES` (default 40).

#### Scenario: Default configuration matches shell script
- **WHEN** no environment variables are set
- **THEN** `MAX_ROUNDS` SHALL be 8, `MAX_REVIEW_CYCLES` SHALL be 3, `POLL_SECONDS` SHALL be 2, `MIN_REVIEW_CYCLES_BEFORE_APPROVAL` SHALL be 2, `REVIEW_EVIDENCE_MIN_MATCH` SHALL be 3

### Requirement: API client with httpx
The orchestrator SHALL use an `ApiClient` class wrapping `httpx.Client` with methods: `create_session()`, `create_terminal()`, `send_input()`, `get_status()`, `get_last_output()`, `exit_terminal()`, `close()`.

#### Scenario: Create session returns terminal ID and session name
- **WHEN** `api.create_session("system_analyst")` is called
- **THEN** it SHALL POST to `/sessions` with provider, agent_profile, and working_directory params, and return a dict with `id` and `session_name`

#### Scenario: Send input to terminal
- **WHEN** `api.send_input(terminal_id, message)` is called
- **THEN** it SHALL POST to `/terminals/{id}/input` with the message param

### Requirement: Review approval with evidence gate
`is_review_approved()` SHALL enforce all conditions: (1) text contains `REVIEW_RESULT: APPROVED`, (2) cycle >= `MIN_REVIEW_CYCLES_BEFORE_APPROVAL`, (3) if `REQUIRE_REVIEW_EVIDENCE` is true, `REVIEW_NOTES:` section exists with sufficient evidence pattern matches (>= `REVIEW_EVIDENCE_MIN_MATCH`).

#### Scenario: Approved with sufficient analyst evidence on cycle 2
- **WHEN** review text contains APPROVED, cycle is 2, and REVIEW_NOTES mentions artifact/proposal, P1/traceability, downstream/contract, and handoff/actionable
- **THEN** `is_review_approved()` SHALL return True

#### Scenario: Approved rejected on cycle 1
- **WHEN** review text contains APPROVED but cycle is 1
- **THEN** `is_review_approved()` SHALL return False regardless of evidence

#### Scenario: Approved rejected with insufficient evidence
- **WHEN** review text contains APPROVED on cycle 2 but only 1 evidence pattern matches
- **THEN** `is_review_approved()` SHALL return False

#### Scenario: Approved without evidence when evidence check disabled
- **WHEN** `REQUIRE_REVIEW_EVIDENCE` is False and review text contains APPROVED on cycle 2
- **THEN** `is_review_approved()` SHALL return True

### Requirement: Feedback condensation
`extract_review_notes()` SHALL extract text from `REVIEW_NOTES:` onward, capped at `MAX_FEEDBACK_LINES`. `extract_test_evidence()` SHALL extract `RESULT:` line plus `EVIDENCE:` section onward, capped at `MAX_FEEDBACK_LINES`. Both SHALL fall back to head-truncated raw text if markers are missing.

#### Scenario: Review notes condensation
- **WHEN** `extract_review_notes()` is called with text containing a `REVIEW_NOTES:` section
- **THEN** it SHALL return only the text from that section onward, up to MAX_FEEDBACK_LINES

#### Scenario: Test evidence condensation
- **WHEN** `extract_test_evidence()` is called with text containing `RESULT:` and `EVIDENCE:` sections
- **THEN** it SHALL return the RESULT line plus the EVIDENCE section, up to MAX_FEEDBACK_LINES

### Requirement: Explore summary condensation
On the first send to each terminal, the full explore summary SHALL be included. On subsequent sends to the same terminal (when `CONDENSE_EXPLORE_ON_REPEAT` is true), it SHALL be replaced with a back-reference: "(Same as initial turn -- refer to your conversation history.)"

#### Scenario: First send includes full summary
- **WHEN** `explore_block_for(terminal_id)` is called for a terminal for the first time
- **THEN** the full `EXPLORE_SUMMARY` text SHALL be returned

#### Scenario: Repeat send returns condensed
- **WHEN** `explore_block_for(terminal_id)` is called again for the same terminal
- **THEN** it SHALL return the back-reference text instead

### Requirement: Prompt builders for all five agents
The orchestrator SHALL have prompt builder functions for analyst, analyst review, programmer, programmer review, and tester. Each SHALL include the appropriate explore block, guard lines, task instructions, and response file instruction matching the shell script's prompt content.

#### Scenario: Analyst prompt structure
- **WHEN** `build_analyst_prompt()` is called
- **THEN** it SHALL contain explore summary, round/cycle numbers, tester and peer analyst feedback, guard lines, task with 5 mandatory ANALYST_SUMMARY sections, and response file instruction

#### Scenario: Programmer prompt condenses upstream on repeat
- **WHEN** `build_programmer_prompt()` is called with cycle > 1 and `CONDENSE_UPSTREAM_ON_REPEAT` is true
- **THEN** the analyst output SHALL be replaced with a back-reference

### Requirement: State file compatibility with shell script
`save_state()` SHALL write JSON with `version: 1` and the same field structure as the shell script: `updated_at`, `api`, `provider`, `wd`, `prompt`, `current_round`, `current_phase`, `final_status`, `session_name`, `terminals` (analyst, peer_analyst, programmer, peer_programmer, tester), `feedback`, `analyst_feedback`, `programmer_feedback`, `outputs` (analyst, analyst_review, programmer, programmer_review, tester).

#### Scenario: State roundtrip
- **WHEN** state is saved and then loaded
- **THEN** all fields SHALL match the original values

#### Scenario: Invalid round in state file defaults to 1
- **WHEN** `current_round` in the state file is not a valid integer
- **THEN** `load_state()` SHALL default it to 1

#### Scenario: Invalid phase in state file defaults to analyst
- **WHEN** `current_phase` in the state file is not a valid phase name
- **THEN** `load_state()` SHALL default it to "analyst"

### Requirement: Orchestration flow
The main loop SHALL execute: Analyst phase (with review cycles) → Programmer phase (with review cycles) → Tester phase → loop on FAIL or exit 0 on PASS. SHALL exit 1 when `MAX_ROUNDS` is exhausted without PASS.

#### Scenario: PASS exits with code 0
- **WHEN** the tester output contains `RESULT: PASS`
- **THEN** the orchestrator SHALL set final_status to "PASS", save state, and exit with code 0

#### Scenario: FAIL loops back to analyst
- **WHEN** the tester output contains `RESULT: FAIL`
- **THEN** the orchestrator SHALL increment the round, reset outputs, extract test evidence as feedback, and loop back to the analyst phase

#### Scenario: MAX_ROUNDS exhausted exits with code 1
- **WHEN** all rounds are completed without a PASS result
- **THEN** the orchestrator SHALL set final_status to "FAIL", save state, and exit with code 1

#### Scenario: Missing analyst output falls back to analyst phase
- **WHEN** the programmer phase starts but `ANALYST_OUT` is empty
- **THEN** the orchestrator SHALL fall back to the analyst phase

### Requirement: Signal handling and cleanup
The orchestrator SHALL handle SIGINT and SIGTERM by saving state and optionally exiting terminals (when `CLEANUP_ON_EXIT` is true).

#### Scenario: SIGINT saves state
- **WHEN** SIGINT is received during execution
- **THEN** the orchestrator SHALL save state and exit with code 130

#### Scenario: Cleanup exits terminals when enabled
- **WHEN** `CLEANUP_ON_EXIT` is true and the orchestrator exits
- **THEN** it SHALL call `exit_terminal` for all 5 terminal IDs

### Requirement: Init and resume
`init_new_run()` SHALL create a session with 5 terminals. Resume mode SHALL load state from the state file and verify all terminal IDs are reachable via the API.

#### Scenario: New run creates 5 terminals
- **WHEN** `init_new_run()` is called
- **THEN** it SHALL create a session with the analyst profile and add 4 more terminals for peer_analyst, programmer, peer_programmer, and tester

#### Scenario: Resume with unreachable terminal fails
- **WHEN** `verify_resume_terminals()` is called and one terminal is unreachable
- **THEN** it SHALL exit with an error message

### Requirement: Auto-resume from in-progress state
When `RESUME` is not explicitly set, the orchestrator SHALL check if a state file exists with `final_status=RUNNING`. If so, it SHALL automatically resume from that state without requiring `RESUME=1`. Completed states (`PASS` or `FAIL`) SHALL NOT trigger auto-resume.

#### Scenario: Auto-resume when state file has RUNNING status
- **WHEN** `RESUME` is not set, and the state file exists with `final_status` equal to `RUNNING`
- **THEN** the orchestrator SHALL load state, verify terminals, and resume the run

#### Scenario: No auto-resume when state file has PASS status
- **WHEN** `RESUME` is not set, and the state file exists with `final_status` equal to `PASS`
- **THEN** the orchestrator SHALL start a new run instead of resuming

#### Scenario: No auto-resume when state file has FAIL status
- **WHEN** `RESUME` is not set, and the state file exists with `final_status` equal to `FAIL`
- **THEN** the orchestrator SHALL start a new run instead of resuming

#### Scenario: No auto-resume when no state file exists
- **WHEN** `RESUME` is not set and no state file exists
- **THEN** the orchestrator SHALL start a new run
