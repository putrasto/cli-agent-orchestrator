## ADDED Requirements

### Requirement: JSON config file loading
The orchestrator SHALL accept an optional JSON config file path as `sys.argv[1]`. If provided and the file exists, it SHALL be parsed as JSON and used as the configuration source. If the file does not exist or is not valid JSON, the orchestrator SHALL exit with a clear error message.

#### Scenario: Config file provided and valid
- **WHEN** `sys.argv[1]` is a path to a valid JSON file
- **THEN** the orchestrator SHALL load configuration from that file

#### Scenario: Config file provided but does not exist
- **WHEN** `sys.argv[1]` is a path to a non-existent file
- **THEN** the orchestrator SHALL exit with code 1 and an error message naming the missing file

#### Scenario: Config file provided but invalid JSON
- **WHEN** `sys.argv[1]` is a path to a file with invalid JSON
- **THEN** the orchestrator SHALL exit with code 1 and an error message describing the parse error

#### Scenario: No config file provided
- **WHEN** `sys.argv` has no second argument
- **THEN** the orchestrator SHALL use environment variables and hardcoded defaults (backward compatible)

### Requirement: Config precedence — env vars override JSON override defaults
The orchestrator SHALL apply configuration in this order (highest to lowest priority): environment variables → JSON file values → hardcoded defaults. An env var that is set to a non-empty string SHALL override the corresponding JSON value. An env var set to empty string SHALL be treated as unset (falls through to JSON or default).

#### Scenario: Env var overrides JSON value
- **WHEN** `MAX_ROUNDS` env var is set to `5` and JSON has `limits.max_rounds: 3`
- **THEN** the effective `MAX_ROUNDS` SHALL be 5

#### Scenario: JSON value overrides hardcoded default
- **WHEN** `MAX_ROUNDS` env var is not set and JSON has `limits.max_rounds: 3`
- **THEN** the effective `MAX_ROUNDS` SHALL be 3

#### Scenario: Hardcoded default used when both absent
- **WHEN** `MAX_ROUNDS` env var is not set and JSON has no `limits.max_rounds`
- **THEN** the effective `MAX_ROUNDS` SHALL be 8

#### Scenario: Empty env var on numeric key treated as unset
- **WHEN** `MAX_ROUNDS` env var is set to empty string `""` and JSON has `limits.max_rounds: 3`
- **THEN** the orchestrator SHALL treat the empty env var as unset and use the JSON value 3

#### Scenario: Empty env var on boolean key treated as unset
- **WHEN** `CLEANUP_ON_EXIT` env var is set to empty string `""` and JSON has `cleanup_on_exit: true`
- **THEN** the orchestrator SHALL treat the empty env var as unset and use the JSON value true

#### Scenario: Env var overrides JSON start agent
- **WHEN** `START_AGENT` env var is `tester` and JSON has `"start_agent": "programmer"`
- **THEN** the effective `START_AGENT` SHALL be `tester`

### Requirement: JSON structure with nested sections
The JSON config file SHALL support these top-level keys: `api`, `provider`, `wd`, `prompt`, `prompt_file`, `project_test_cmd`, `start_agent`, `agents`, `limits`, `condensation`, `handoff`, `post_processing`, `cleanup_on_exit`, `resume`, `state_file`. Nested sections SHALL map to flat config keys:
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
- `post_processing.openspec_archive` → `POST_OPENSPEC_ARCHIVE`
- `post_processing.git_commit` → `POST_GIT_COMMIT`

#### Scenario: Nested limits section maps correctly
- **WHEN** JSON contains `{"limits": {"max_rounds": 3, "max_review_cycles": 2}}`
- **THEN** `MAX_ROUNDS` SHALL be 3 and `MAX_REVIEW_CYCLES` SHALL be 2

#### Scenario: Unknown top-level keys cause fatal error
- **WHEN** JSON contains `{"descripion": "my run", "limits": {"max_rounds": 3}}`
- **THEN** the orchestrator SHALL exit with code 1 and an error message identifying `descripion` as an unknown config key

#### Scenario: Condensation section maps test evidence limit
- **WHEN** JSON contains `{"condensation": {"max_test_evidence_lines": 80}}`
- **THEN** `MAX_TEST_EVIDENCE_LINES` SHALL be 80

#### Scenario: Post-processing section maps correctly
- **WHEN** JSON contains `{"post_processing": {"openspec_archive": true, "git_commit": true}}`
- **THEN** `POST_OPENSPEC_ARCHIVE` SHALL be true and `POST_GIT_COMMIT` SHALL be true

#### Scenario: Post-processing defaults to disabled
- **WHEN** JSON has no `post_processing` section
- **THEN** `POST_OPENSPEC_ARCHIVE` SHALL be false and `POST_GIT_COMMIT` SHALL be false

### Requirement: Per-agent provider and profile configuration
The `agents` section SHALL map each of the 5 roles to an object with optional `provider` and `profile` fields. If `agents` is omitted, all roles SHALL use the top-level `provider` default and their default profile. If a role's `provider` is omitted, it SHALL inherit the top-level `provider`. If a role's `profile` is omitted, it SHALL use the default profile for that role.

Default profiles: `analyst` → `system_analyst`, `peer_analyst` → `peer_system_analyst`, `programmer` → `programmer`, `peer_programmer` → `peer_programmer`, `tester` → `tester`.

#### Scenario: Full agent config with mixed providers
- **WHEN** JSON contains `{"agents": {"analyst": {"provider": "claude_code"}, "peer_analyst": {"provider": "codex"}}}`
- **THEN** analyst SHALL use `claude_code` and peer_analyst SHALL use `codex`, both with their default profiles

#### Scenario: Agent with custom profile
- **WHEN** JSON contains `{"agents": {"analyst": {"provider": "claude_code", "profile": "custom_analyst"}}}`
- **THEN** analyst SHALL use provider `claude_code` and profile `custom_analyst`

#### Scenario: Agents section omitted entirely
- **WHEN** JSON has no `agents` key and top-level `provider` is `codex`
- **THEN** all 5 roles SHALL use `codex` with their default profiles

#### Scenario: Agent role missing provider inherits top-level
- **WHEN** JSON has `{"provider": "claude_code", "agents": {"analyst": {"profile": "custom_analyst"}}}`
- **THEN** analyst SHALL use `claude_code` (inherited) with `custom_analyst` profile

### Requirement: Agent config validation — strict fail-fast
The orchestrator SHALL validate the `agents` config at startup before creating any terminals. Unknown role names SHALL cause a fatal error. Provider values SHALL be one of `codex`, `claude_code`, `q_cli`, `kiro_cli`; invalid values SHALL cause a fatal error.

#### Scenario: Unknown role name causes fatal error
- **WHEN** JSON contains `{"agents": {"peer_anlyst": {"provider": "codex"}}}`
- **THEN** the orchestrator SHALL exit with code 1 and an error message identifying `peer_anlyst` as an unknown role

#### Scenario: Invalid provider causes fatal error
- **WHEN** JSON contains `{"agents": {"analyst": {"provider": "gpt4"}}}`
- **THEN** the orchestrator SHALL exit with code 1 and an error message identifying `gpt4` as an invalid provider

#### Scenario: Valid config passes validation
- **WHEN** all roles use recognized names and valid providers
- **THEN** validation SHALL pass and terminal creation SHALL proceed

### Requirement: Start agent option
The orchestrator SHALL support `start_agent`/`START_AGENT` with allowed values: `analyst`, `peer_analyst`, `programmer`, `peer_programmer`, `tester`. If unset, default SHALL be `analyst`. Invalid values SHALL cause a fatal startup error. This option selects the first dispatched role on fresh runs.

#### Scenario: Start agent omitted uses default
- **WHEN** neither JSON `start_agent` nor env `START_AGENT` is set
- **THEN** effective `START_AGENT` SHALL be `analyst`

#### Scenario: Valid start agent from JSON
- **WHEN** JSON has `"start_agent": "programmer"` and env `START_AGENT` is unset
- **THEN** effective `START_AGENT` SHALL be `programmer`

#### Scenario: Invalid start agent causes fatal error
- **WHEN** JSON has `"start_agent": "qa_reviewer"`
- **THEN** the orchestrator SHALL exit with code 1 and an error message identifying `qa_reviewer` as invalid

### Requirement: Sample config files
The orchestrator directory SHALL include sample JSON config files demonstrating fresh, incremental, and resume scenarios.

#### Scenario: Fresh config sample exists
- **WHEN** a user looks for a config example
- **THEN** `config-fresh.json` SHALL exist with all sections populated including mixed-provider agents and `post_processing`

#### Scenario: Incremental config sample exists
- **WHEN** a user wants to run an incremental change on an existing project
- **THEN** `config-incremental.json` SHALL exist with all sections populated, noting that incremental behavior is driven by the prompt file content (not a config flag)

#### Scenario: Resume config sample exists
- **WHEN** a user wants to resume an interrupted run
- **THEN** `config-resume.json` SHALL exist with `resume: true` and minimal other settings
