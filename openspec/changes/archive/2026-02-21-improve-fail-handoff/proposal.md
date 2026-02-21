## Why

When the tester reports FAIL, the orchestrator loops back to the system analyst with only the condensed tester evidence. The analyst has no visibility into what the programmer actually changed — it must re-explore the codebase from scratch to understand the current state. This wastes agent tokens on redundant exploration and risks the analyst misdiagnosing whether the failure is a spec problem or an implementation problem. Additionally, test failure evidence is truncated to 30 lines (`MAX_FEEDBACK_LINES`), which can cut off the tester's "Recommended next fix" section on complex failures.

## What Changes

- Carry a condensed programmer summary across FAIL retries, available to the system analyst only (no other agents see it)
- Persist this programmer retry context in `save_state()`/`load_state()` so it survives resume
- Split the line limit: keep `MAX_FEEDBACK_LINES=30` for peer review condensation, add `MAX_TEST_EVIDENCE_LINES=120` for tester FAIL evidence
- Wire `MAX_TEST_EVIDENCE_LINES` through the full config pipeline: `_CONFIG_KEYS`, JSON config mapping, sample configs, env var, `_apply_config()`
- Include the programmer retry context in `build_analyst_prompt()` for round > 1 only

## Capabilities

### New Capabilities
- `fail-retry-context`: Carrying condensed programmer summary to analyst on FAIL retry, including state persistence and prompt integration
- `test-evidence-limit`: Separate line limit for tester FAIL evidence, distinct from peer review feedback limit

### Modified Capabilities
- `json-config`: Adding `condensation.max_test_evidence_lines` mapping to `MAX_TEST_EVIDENCE_LINES`

## Impact

- **Code**: `examples/agnostic-3agents/run_orchestrator_loop.py` — new global, `_CONFIG_KEYS` entry, `_apply_config()`, `save_state()`, `load_state()`, `extract_test_evidence()`, `build_analyst_prompt()`, FAIL branch in main loop
- **Config spec**: `openspec/specs/json-config/spec.md` — new mapping entry
- **Sample configs**: `config-fresh.json`, `config-incremental.json` — add `max_test_evidence_lines` to condensation section
- **Tests**: `test/examples/test_orchestrator_loop_unit.py` — new tests for retry context persistence, separate evidence line limit, existing `extract_test_evidence` tests updated for new limit
- **No API changes**: This is internal orchestrator logic only
- **No agent profile changes**: The analyst prompt is built by the orchestrator, not the profile
