## 1. Add MAX_TEST_EVIDENCE_LINES to config pipeline

- [x] 1.1 Add `("condensation.max_test_evidence_lines", "MAX_TEST_EVIDENCE_LINES", 120, int)` to `_CONFIG_KEYS` in `run_orchestrator_loop.py`
- [x] 1.2 Add `MAX_TEST_EVIDENCE_LINES` to the `global` declaration in `_apply_config()` and assign from `cfg["MAX_TEST_EVIDENCE_LINES"]`
- [x] 1.3 Update `extract_test_evidence()` to use `MAX_TEST_EVIDENCE_LINES` instead of `MAX_FEEDBACK_LINES` (both the structured and fallback truncation paths)

## 2. Add programmer_context_for_retry global and FAIL branch logic

- [x] 2.1 Add module-level global `programmer_context_for_retry: str = ""` near the other feedback globals (around line 826)
- [x] 2.2 In the FAIL branch of the tester phase (around line 1294), set `programmer_context_for_retry = condense_programmer_for_tester(outputs["programmer"])` before clearing `outputs`

## 3. Persist programmer retry context in state

- [x] 3.1 Add `"programmer_context_for_retry": programmer_context_for_retry` to the state dict in `save_state()`
- [x] 3.2 In `load_state()`, restore `programmer_context_for_retry` using `data.get("programmer_context_for_retry", "")` and declare it `global`

## 4. Inject programmer context into analyst prompt

- [x] 4.1 In `build_analyst_prompt()`, after the "Latest tester feedback:" block and before "Latest peer analyst feedback:", add a conditional block: if `round_num > 1` and `programmer_context_for_retry` is non-empty, include `"Previous round programmer changes (context only):\n" + programmer_context_for_retry`

## 5. Update sample configs

- [x] 5.1 Add `"max_test_evidence_lines": 120` to the `condensation` section in `config-fresh.json`
- [x] 5.2 Add `"max_test_evidence_lines": 120` to the `condensation` section in `config-incremental.json`

## 6. Tests

- [x] 6.1 Add test: `extract_test_evidence()` truncates at `MAX_TEST_EVIDENCE_LINES` (120) not `MAX_FEEDBACK_LINES` (30)
- [x] 6.2 Add test: `extract_test_evidence()` fallback path uses `MAX_TEST_EVIDENCE_LINES`
- [x] 6.3 Add test: `extract_review_notes()` still truncates at `MAX_FEEDBACK_LINES` (30) — unchanged
- [x] 6.4 Add test: `save_state()`/`load_state()` round-trip preserves `programmer_context_for_retry`
- [x] 6.5 Add test: `load_state()` on old state file without `programmer_context_for_retry` defaults to `""`
- [x] 6.6 Add test: `build_analyst_prompt()` includes programmer context when `round_num > 1` and context is non-empty
- [x] 6.7 Add test: `build_analyst_prompt()` excludes programmer context when `round_num == 1`
- [x] 6.8 Add test: `build_analyst_prompt()` excludes programmer context when context is empty string
- [x] 6.9 Add test: `MAX_TEST_EVIDENCE_LINES` loads from JSON config `condensation.max_test_evidence_lines`
- [x] 6.10 Add test: `build_programmer_prompt()` does not contain "Previous round programmer changes" when `programmer_context_for_retry` is non-empty
- [x] 6.11 Add test: `build_programmer_review_prompt()` does not contain "Previous round programmer changes" when `programmer_context_for_retry` is non-empty
- [x] 6.12 Add test: `build_analyst_review_prompt()` does not contain "Previous round programmer changes" when `programmer_context_for_retry` is non-empty
- [x] 6.13 Add test: `build_tester_prompt()` does not contain "Previous round programmer changes" when `programmer_context_for_retry` is non-empty
- [x] 6.14 Add test: `MAX_TEST_EVIDENCE_LINES` defaults to 120 when neither env var nor JSON is set
- [x] 6.15 Add test: env var `MAX_TEST_EVIDENCE_LINES` overrides JSON `condensation.max_test_evidence_lines`
- [x] 6.16 Add test: `extract_test_evidence()` truncates at a custom non-default value (e.g., `MAX_TEST_EVIDENCE_LINES=60` truncates at 60 lines)

## 7. Run full test suite

- [x] 7.1 Run `uv run pytest -q test/examples/test_orchestrator_loop_unit.py` and verify all tests pass
- [x] 7.2 Run `uv run pytest -v` and verify no regressions across the full suite
