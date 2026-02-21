## ADDED Requirements

### Requirement: Separate line limit for tester FAIL evidence
The orchestrator SHALL support a `MAX_TEST_EVIDENCE_LINES` configuration with default value 120. The `extract_test_evidence()` function SHALL use `MAX_TEST_EVIDENCE_LINES` instead of `MAX_FEEDBACK_LINES` for truncating tester output. The `extract_review_notes()` function SHALL continue using `MAX_FEEDBACK_LINES` unchanged.

#### Scenario: Test evidence uses dedicated limit
- **WHEN** `MAX_TEST_EVIDENCE_LINES` is 120 and `MAX_FEEDBACK_LINES` is 30
- **THEN** `extract_test_evidence()` SHALL truncate output at 120 lines
- **AND** `extract_review_notes()` SHALL truncate output at 30 lines

#### Scenario: Test evidence respects custom limit
- **WHEN** `MAX_TEST_EVIDENCE_LINES` is set to 60
- **THEN** `extract_test_evidence()` SHALL truncate output at 60 lines

#### Scenario: Fallback path also uses test evidence limit
- **WHEN** tester output has no RESULT/EVIDENCE markers and `MAX_TEST_EVIDENCE_LINES` is 120
- **THEN** `extract_test_evidence()` SHALL fall back to the first 120 lines of raw text

### Requirement: MAX_TEST_EVIDENCE_LINES in config pipeline
`MAX_TEST_EVIDENCE_LINES` SHALL be configurable via environment variable `MAX_TEST_EVIDENCE_LINES` and JSON config key `condensation.max_test_evidence_lines`, following the same precedence rules as all other config keys (env var > JSON > default).

#### Scenario: Default value when not configured
- **WHEN** neither env var `MAX_TEST_EVIDENCE_LINES` nor JSON `condensation.max_test_evidence_lines` is set
- **THEN** the effective `MAX_TEST_EVIDENCE_LINES` SHALL be 120

#### Scenario: JSON config overrides default
- **WHEN** JSON has `{"condensation": {"max_test_evidence_lines": 80}}` and env var is unset
- **THEN** the effective `MAX_TEST_EVIDENCE_LINES` SHALL be 80

#### Scenario: Env var overrides JSON
- **WHEN** env var `MAX_TEST_EVIDENCE_LINES` is `60` and JSON has `condensation.max_test_evidence_lines: 80`
- **THEN** the effective `MAX_TEST_EVIDENCE_LINES` SHALL be 60

### Requirement: Sample configs include max_test_evidence_lines
The sample config files `config-fresh.json` and `config-incremental.json` SHALL include `max_test_evidence_lines: 120` in their `condensation` section.

#### Scenario: config-fresh.json has test evidence limit
- **WHEN** reading `config-fresh.json`
- **THEN** `condensation.max_test_evidence_lines` SHALL be present with value 120

#### Scenario: config-incremental.json has test evidence limit
- **WHEN** reading `config-incremental.json`
- **THEN** `condensation.max_test_evidence_lines` SHALL be present with value 120
