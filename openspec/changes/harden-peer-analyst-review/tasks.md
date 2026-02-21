## 1. Agent Profile

- [x] 1.1 Rewrite `examples/codex-3agents/peer_system_analyst.md` with adversarial-by-default stance, section-by-section rejection criteria, codebase verification requirement, and minimum depth requirement
- [x] 1.2 Verify profile mentions all 5 ANALYST_SUMMARY sections (Scope, OpenSpec artifacts, Implementation notes, Risks, Downstream impact)

## 2. Evidence Patterns

- [x] 2.1 Replace `ANALYST_EVIDENCE_PATTERNS` in `run_orchestrator_loop.py` with co-occurrence patterns (domain term + assessment term)
- [x] 2.2 Verify old trivial reviews (e.g., "artifacts and downstream handoff are fine") no longer pass the evidence gate

## 3. Review Prompt Builder

- [x] 3.1 Update `build_analyst_review_prompt()` with hardened checklist: rejection criteria per section, "default stance is REVISE", codebase verification instruction
- [x] 3.2 Verify prompt contains all rejection criteria and verification instruction

## 4. Tests

- [x] 4.1 Update `test_approved_with_sufficient_analyst_evidence` to use co-occurrence evidence text
- [x] 4.2 Add test for trivial review rejection (domain words without assessment co-occurrence)
- [x] 4.3 Update `test_analyst_review_prompt_has_required_parts` for new checklist content
- [x] 4.4 Run full test suite and verify all 75+ tests pass
