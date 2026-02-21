## 1. Configuration and Imports

- [x] 1.1 Create `examples/codex-3agents/run_orchestrator_loop.py` with imports (json, os, re, signal, sys, time, pathlib, datetime, httpx)
- [x] 1.2 Define all configuration from environment variables with same names/defaults as shell script
- [x] 1.3 Define response file mapping dict, regex patterns, and phase constants

## 2. Core Infrastructure

- [x] 2.1 Implement `log()` timestamped print function
- [x] 2.2 Implement `ApiClient` class with httpx wrapping all 7 API methods (create_session, create_terminal, send_input, get_status, get_last_output, exit_terminal, close)
- [x] 2.3 Create module-level `api` singleton

## 3. File-Based Handoff

- [x] 3.1 Implement `response_path_for(role)` returning absolute Path for each role
- [x] 3.2 Implement `clear_stale_response(role)` to delete existing response files
- [x] 3.3 Implement `ensure_response_dir()` to create `.tmp/agent-responses/` directory
- [x] 3.4 Implement `response_file_instruction(role)` returning the instruction block to append to prompts
- [x] 3.5 Implement `wait_for_response_file(role, terminal_id, timeout)` with poll loop, status gate, and fallback
- [x] 3.6 Implement `send_and_wait(terminal_id, role, message)` convenience function

## 4. Review and Feedback Logic

- [x] 4.1 Implement `is_review_approved()` with APPROVED regex, cycle gate, evidence patterns for analyst and programmer roles
- [x] 4.2 Implement `_extract_section()` for regex-based section extraction
- [x] 4.3 Implement `extract_review_notes()` with REVIEW_NOTES condensation and MAX_FEEDBACK_LINES
- [x] 4.4 Implement `extract_test_evidence()` with RESULT + EVIDENCE extraction

## 5. Explore and Upstream Condensation

- [x] 5.1 Implement `explore_block_for(terminal_id)` with set-based tracking and condensation
- [x] 5.2 Implement upstream condensation in `build_programmer_prompt()` for cycle > 1

## 6. Prompt Builders

- [x] 6.1 Implement `build_analyst_prompt()` with explore block, round/cycle, feedback, guard lines, 5 mandatory sections, and response file instruction
- [x] 6.2 Implement `build_analyst_review_prompt()` with analyst output, review checklist, and response file instruction
- [x] 6.3 Implement `build_programmer_prompt()` with explore block, analyst output, guard lines, autonomy rules, and response file instruction
- [x] 6.4 Implement `build_programmer_review_prompt()` with programmer output, review task, test command instruction, and response file instruction
- [x] 6.5 Implement `build_tester_prompt()` with scenario test, programmer output, guard lines, and response file instruction
- [x] 6.6 Implement `_test_command_instruction()` helper

## 7. State Management

- [x] 7.1 Define module-level state globals (session_name, terminal_ids, current_round, current_phase, final_status, feedback vars, outputs)
- [x] 7.2 Implement `save_state()` writing version-1 JSON compatible with shell script format
- [x] 7.3 Implement `load_state()` with validation (round defaults to 1, phase defaults to analyst)

## 8. Init and Resume

- [x] 8.1 Implement `init_new_run()` creating session + 5 terminals
- [x] 8.2 Implement `verify_resume_terminals()` checking all 5 terminal IDs are reachable
- [x] 8.3 Implement `log_terminal_ids()` helper

## 9. Main Loop and Entry Point

- [x] 9.1 Implement signal handlers for SIGINT/SIGTERM saving state and cleaning up
- [x] 9.2 Implement prompt loading (PROMPT_FILE, resume from state, validation)
- [x] 9.3 Implement prompt structure validation (EXPLORE_HEADER, SCENARIO_HEADER, section extraction)
- [x] 9.4 Implement analyst phase with review cycles and approval gate
- [x] 9.5 Implement programmer phase with review cycles, upstream condensation, and approval gate
- [x] 9.6 Implement tester phase with PASS/FAIL logic and feedback extraction
- [x] 9.7 Implement MAX_ROUNDS exhaustion exit
- [x] 9.8 Implement `cleanup()` with optional terminal exit
- [x] 9.9 Implement `_extract_prompt_section()` for header-based section extraction

## 10. Testing

- [x] 10.1 Create `test/examples/__init__.py` and `test/examples/test_orchestrator_loop_unit.py`
- [x] 10.2 Write tests for `_extract_prompt_section()` (4 cases)
- [x] 10.3 Write tests for `_extract_section()` (3 cases)
- [x] 10.4 Write tests for `is_review_approved()` (7 cases covering approval, rejection, cycle gate, evidence)
- [x] 10.5 Write tests for `extract_review_notes()` (4 cases)
- [x] 10.6 Write tests for `extract_test_evidence()` (2 cases)
- [x] 10.7 Write tests for `explore_block_for()` (4 cases)
- [x] 10.8 Write tests for all 5 prompt builders (6 cases)
- [x] 10.9 Write tests for `response_file_instruction()` and file handoff helpers (5 cases)
- [x] 10.10 Write tests for state save/load roundtrip and JSON format compatibility (5 cases)
- [x] 10.11 Write tests for `_test_command_instruction()` (2 cases)
- [x] 10.12 Verify syntax with `ast.parse` and run full test suite (43 tests pass)
