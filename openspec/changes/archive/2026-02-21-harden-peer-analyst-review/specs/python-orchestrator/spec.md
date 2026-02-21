## MODIFIED Requirements

### Requirement: Review approval with evidence gate
`is_review_approved()` SHALL enforce all conditions: (1) text contains `REVIEW_RESULT: APPROVED`, (2) cycle >= `MIN_REVIEW_CYCLES_BEFORE_APPROVAL`, (3) if `REQUIRE_REVIEW_EVIDENCE` is true, `REVIEW_NOTES:` section exists with sufficient evidence pattern matches (>= `REVIEW_EVIDENCE_MIN_MATCH`).

Analyst evidence patterns SHALL require co-occurrence of a domain term and an assessment term:
- Artifact/spec term + verdict (e.g., "proposal verified", "spec incomplete")
- Priority/traceability term + coverage language (e.g., "P1 coverage gap", "traceability confirmed")
- Downstream/contract term + specific module or file reference
- Handoff term + concrete next-step language (e.g., "handoff includes 3 action items")

#### Scenario: Approved with sufficient analyst evidence using co-occurrence patterns
- **WHEN** review text contains APPROVED, cycle is 2, and REVIEW_NOTES contains "proposal verified", "P1 traceability confirmed", "downstream contract for api module", and "handoff includes concrete steps"
- **THEN** `is_review_approved()` SHALL return True

#### Scenario: Trivial review rejected despite containing domain keywords
- **WHEN** review text contains APPROVED, cycle is 2, and REVIEW_NOTES contains only "looks good, artifacts and downstream handoff are fine" (domain words without assessment co-occurrence)
- **THEN** `is_review_approved()` SHALL return False

#### Scenario: Approved rejected on cycle 1
- **WHEN** review text contains APPROVED but cycle is 1
- **THEN** `is_review_approved()` SHALL return False regardless of evidence

#### Scenario: Approved rejected with insufficient evidence
- **WHEN** review text contains APPROVED on cycle 2 but only 1 evidence pattern matches
- **THEN** `is_review_approved()` SHALL return False

#### Scenario: Approved without evidence when evidence check disabled
- **WHEN** `REQUIRE_REVIEW_EVIDENCE` is False and review text contains APPROVED on cycle 2
- **THEN** `is_review_approved()` SHALL return True

## ADDED Requirements

### Requirement: Adversarial peer analyst review prompt
`build_analyst_review_prompt()` SHALL include a checklist that requires the reviewer to verify each ANALYST_SUMMARY section against concrete rejection criteria:
- Scope: must reference specific files or modules
- OpenSpec artifacts: must list artifact filenames
- Implementation notes: must contain at least 3 action items
- Risks: must not be "none" or single-line without mitigation
- Downstream impact: must not be "N/A" or missing

The prompt SHALL instruct the reviewer that its default stance is REVISE and it must justify APPROVED.

#### Scenario: Review prompt contains rejection criteria
- **WHEN** `build_analyst_review_prompt()` is called
- **THEN** the prompt SHALL contain "default stance is REVISE" and rejection criteria for all 5 ANALYST_SUMMARY sections

#### Scenario: Review prompt requires codebase verification
- **WHEN** `build_analyst_review_prompt()` is called
- **THEN** the prompt SHALL instruct the reviewer to verify at least 2 file paths mentioned in the analyst output exist in the codebase

### Requirement: Adversarial peer analyst agent profile
The `peer_system_analyst.md` agent profile SHALL define the reviewer as adversarial-by-default with:
- Default recommendation: REVISE
- Section-by-section rejection criteria for each ANALYST_SUMMARY section
- Codebase verification requirement (check file paths exist)
- Minimum depth requirement (one-liner sections trigger REVISE)

#### Scenario: Profile instructs adversarial default
- **WHEN** the peer system analyst agent profile is loaded
- **THEN** it SHALL contain instruction that default recommendation is REVISE and reviewer must justify APPROVED
