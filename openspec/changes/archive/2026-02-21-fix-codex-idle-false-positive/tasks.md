# Tasks

## 1. Fix USER_PREFIX_PATTERN newline overmatch

- [x] 1.1 In `src/cli_agent_orchestrator/providers/codex.py`, change `USER_PREFIX_PATTERN` from `r"^\s*(?:You\b|›\s+\S)"` to `r"^\s*(?:You\b|›[ \t]+\S)"` so `\s+` only matches horizontal whitespace

## 2. Fix processing keyword override of idle detection

- [x] 2.1 In `_analyze_clean_output()`, change `has_v104_idle_prompt` to use `not has_active_work_ui` instead of `not has_processing_signal`
- [x] 2.2 In `_analyze_clean_output()`, change the status decision branch to use `not has_active_work_ui` instead of `not has_processing_signal`

## 3. Tighten ACTIVE_WORK_UI_PATTERN

- [x] 3.1 In `ACTIVE_WORK_UI_PATTERN`, change `\bExploring\b` to `•\s+Exploring\b` to anchor it to the Codex bullet prefix

## 4. Tests

- [x] 4.1 Verify the 2 existing failing tests now pass: `test_get_status_completed_with_v104_prompt_and_footer` and `test_get_status_completed_with_v104_user_and_assistant_markers`
- [x] 4.2 Add test `test_get_status_idle_despite_narrative_processing_keyword`: terminal output has "stop running commands" in narrative + idle prompt at end → status SHALL be IDLE or COMPLETED, not PROCESSING
- [x] 4.3 Add test `test_get_status_processing_with_active_work_ui_overrides_idle`: terminal output has "esc to interrupt" UI + idle prompt from previous turn → status SHALL be PROCESSING
- [x] 4.4 Add test `test_get_status_idle_despite_narrative_exploring`: terminal output has "I was exploring the codebase" in narrative (no bullet prefix) + idle prompt → status SHALL be IDLE or COMPLETED, not PROCESSING
- [x] 4.5 Add test `test_user_prefix_pattern_no_cross_line_match`: verify `USER_PREFIX_PATTERN` does NOT match `›\n100% context left` and DOES match `› Reply with READY`
- [x] 4.6 Run full Codex provider test suite with `uv run pytest test/providers/test_codex_provider_unit.py -v` — all tests pass
