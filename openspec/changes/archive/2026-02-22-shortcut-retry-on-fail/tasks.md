## 1. FAIL Handler — Phase Transition and Output Clearing

- [x] 1.1 Change FAIL handler to set `current_phase = PHASE_PROGRAMMER` instead of `PHASE_ANALYST`
- [x] 1.2 Replace blanket `outputs` clearing with selective clearing: clear only `outputs["programmer"]`, `outputs["programmer_review"]`, `outputs["tester"]`; preserve `outputs["analyst"]` and `outputs["analyst_review"]`

## 2. Programmer Prompt — Retry Context

- [x] 2.1 Add `round_num > 1` branch in `build_programmer_prompt()` that switches to retry prompt logic (parameter already exists in signature)
- [x] 2.2 In retry branch: replace "System analyst handoff" block with "Test failure feedback" block using the `feedback` global
- [x] 2.3 On `round_num > 1`: include `programmer_context_for_retry` as "Your previous changes (context):" when non-empty
- [x] 2.4 On `round_num > 1`: add instructions to use `/opsx:explore` to investigate failure and `/opsx:ff` to update artifacts if needed

## 3. Remove Analyst Retry Context

- [x] 3.1 Remove `programmer_context_for_retry` block from `build_analyst_prompt()` (lines 728-731: the `if round_num > 1 and programmer_context_for_retry` block)

## 4. Tests

- [x] 4.1 Update existing FAIL-retry tests: verify `current_phase` is `PHASE_PROGRAMMER` (not `PHASE_ANALYST`) after FAIL
- [x] 4.2 Add test: selective output clearing — analyst outputs preserved, programmer/tester outputs cleared on FAIL
- [x] 4.3 Add test: retry programmer prompt contains "Test failure feedback:" and not "System analyst handoff:"
- [x] 4.4 Add test: retry programmer prompt includes `programmer_context_for_retry` when non-empty
- [x] 4.5 Add test: retry programmer prompt excludes retry context when `programmer_context_for_retry` is empty
- [x] 4.6 Add test: round 1 programmer prompt unchanged (still has "System analyst handoff:")
- [x] 4.7 Add test: resume with `current_round=2, current_phase=programmer` does not fall back to analyst
- [x] 4.8 Add test: `START_AGENT=programmer` with FAIL uses short retry (no analyst fallback)
