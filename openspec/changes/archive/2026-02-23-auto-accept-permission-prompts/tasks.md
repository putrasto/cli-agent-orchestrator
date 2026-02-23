## 1. Claude Code Provider — Permission Prompt Detection

- [x] 1.1 Add `PERMISSION_PROMPT_PATTERNS` list constant in `src/cli_agent_orchestrator/providers/claude_code.py` (after existing pattern constants): `[r"Would you like to run", r"Do you want to .* outside", r"Allow .* to run"]`
- [x] 1.2 Add permission prompt detection logic in `get_status()` — after the existing `WAITING_USER_ANSWER_PATTERN` check (line 206) and before the idle prompt scanning block (line 208): iterate patterns against `tail_output`, if any matches and no `IDLE_PROMPT_PATTERN` after it, return `WAITING_USER_ANSWER`

## 2. Orchestrator Loop — Auto-Accept Logic

- [x] 2.1 Add `AUTO_ACCEPT_PERMISSIONS` env var parsing (default `0`) alongside other env vars in `examples/agnostic-3agents/run_orchestrator_loop.py`
- [x] 2.2 Add module-level state variables: `_last_permission_accept: dict[str, float]`, `_permission_accept_count: dict[str, int]`, `PERMISSION_ACCEPT_COOLDOWN = 5.0`, `MAX_PERMISSION_ACCEPTS_PER_TURN = 20`
- [x] 2.3 Add `waiting_user_answer` handling in `wait_for_response_file()` after the error check (line 469) and before the file-exists check (line 471): when opted in — log with terminal snippet, send `y`, respect cooldown (5s) and safety cap (20); when not opted in — log warning only
- [x] 2.4 Reset `_permission_accept_count[terminal_id] = 0` at the start of `send_and_wait()` (line 570)

## 3. Tests

- [x] 3.1 Add provider tests in `test/providers/test_claude_code_provider_unit.py`: active permission prompt → WAITING_USER_ANSWER, sandbox escape variant → WAITING_USER_ANSWER, stale prompt (idle after) → not WAITING_USER_ANSWER, spinner + permission text → PROCESSING
- [x] 3.2 Add orchestrator tests in `test/examples/test_orchestrator_loop_unit.py`: auto-accept sends `y` when opted in then agent completes, warning logged when not opted in, cooldown prevents rapid sends, safety cap exceeded raises RuntimeError, counter resets per turn

## 4. Verification

- [x] 4.1 Run provider tests: `.venv/bin/pytest test/providers/test_claude_code_provider_unit.py -v`
- [x] 4.2 Run orchestrator tests: `.venv/bin/pytest test/examples/test_orchestrator_loop_unit.py -v`
- [x] 4.3 Syntax check both modified source files
