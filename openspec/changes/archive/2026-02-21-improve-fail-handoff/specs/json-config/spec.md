## MODIFIED Requirements

### Requirement: JSON structure with nested sections
The JSON config file SHALL support these top-level keys: `api`, `provider`, `wd`, `prompt`, `prompt_file`, `project_test_cmd`, `start_agent`, `agents`, `limits`, `condensation`, `handoff`, `cleanup_on_exit`, `resume`, `state_file`. Nested sections SHALL map to flat config keys:
- `start_agent` → `START_AGENT`
- `limits.max_rounds` → `MAX_ROUNDS`
- `limits.max_review_cycles` → `MAX_REVIEW_CYCLES`
- `limits.min_review_cycles_before_approval` → `MIN_REVIEW_CYCLES_BEFORE_APPROVAL`
- `limits.poll_seconds` → `POLL_SECONDS`
- `limits.require_review_evidence` → `REQUIRE_REVIEW_EVIDENCE`
- `limits.review_evidence_min_match` → `REVIEW_EVIDENCE_MIN_MATCH`
- `condensation.condense_cross_phase` → `CONDENSE_CROSS_PHASE`
- `condensation.max_cross_phase_lines` → `MAX_CROSS_PHASE_LINES`
- `condensation.condense_upstream_on_repeat` → `CONDENSE_UPSTREAM_ON_REPEAT`
- `condensation.condense_explore_on_repeat` → `CONDENSE_EXPLORE_ON_REPEAT`
- `condensation.condense_review_feedback` → `CONDENSE_REVIEW_FEEDBACK`
- `condensation.max_feedback_lines` → `MAX_FEEDBACK_LINES`
- `condensation.max_test_evidence_lines` → `MAX_TEST_EVIDENCE_LINES`
- `handoff.strict_file_handoff` → `STRICT_FILE_HANDOFF`
- `handoff.idle_grace_seconds` → `IDLE_GRACE_SECONDS`
- `handoff.response_timeout` → `RESPONSE_TIMEOUT`

#### Scenario: Nested limits section maps correctly
- **WHEN** JSON contains `{"limits": {"max_rounds": 3, "max_review_cycles": 2}}`
- **THEN** `MAX_ROUNDS` SHALL be 3 and `MAX_REVIEW_CYCLES` SHALL be 2

#### Scenario: Unknown top-level keys cause fatal error
- **WHEN** JSON contains `{"descripion": "my run", "limits": {"max_rounds": 3}}`
- **THEN** the orchestrator SHALL exit with code 1 and an error message identifying `descripion` as an unknown config key

#### Scenario: Condensation section maps test evidence limit
- **WHEN** JSON contains `{"condensation": {"max_test_evidence_lines": 80}}`
- **THEN** `MAX_TEST_EVIDENCE_LINES` SHALL be 80
