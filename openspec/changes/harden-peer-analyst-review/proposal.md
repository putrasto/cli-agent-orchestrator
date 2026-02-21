## Why

The peer system analyst reviewer almost always approves on the first eligible cycle. The agent profile is too vague — it lists responsibilities but defines no rejection bar. The evidence patterns in the orchestrator are too loose (common words like "artifact", "downstream" match trivially). This means the review cycle burns tokens without catching real quality issues in analyst output.

## What Changes

- Rewrite `peer_system_analyst.md` agent profile to be adversarial-by-default: the reviewer must justify APPROVED, not justify REVISE.
- Add concrete rejection criteria: missing ANALYST_SUMMARY sections, vague scope, no file paths in implementation notes, unmitigated risks, one-liner sections.
- Add verification tasks: reviewer must check that files/paths mentioned by analyst exist in the codebase.
- Tighten `ANALYST_EVIDENCE_PATTERNS` in the orchestrator so trivial reviews don't pass the evidence gate.
- Update the review prompt builder (`build_analyst_review_prompt`) with a more demanding checklist.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `python-orchestrator`: Tighter evidence patterns for analyst review and updated review prompt builder.

## Impact

- `examples/codex-3agents/peer_system_analyst.md` — rewritten agent profile
- `examples/codex-3agents/run_orchestrator_loop.py` — updated `ANALYST_EVIDENCE_PATTERNS`, `build_analyst_review_prompt()`
- `test/examples/test_orchestrator_loop_unit.py` — updated tests for new evidence patterns and prompt content
