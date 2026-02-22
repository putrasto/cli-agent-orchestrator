## MODIFIED Requirements

### Requirement: Configuration via environment variables
The orchestrator SHALL read configuration from a JSON config file (if provided as `sys.argv[1]`), environment variables, and hardcoded defaults, in that precedence order (env vars highest). Existing environment variable names/defaults SHALL remain unchanged, and two new variables SHALL be added: `POST_OPENSPEC_ARCHIVE` (default false) and `POST_GIT_COMMIT` (default false). The `agents` section (per-agent provider/profile) SHALL be JSON-only with no env var mapping.

#### Scenario: Default configuration matches shell script
- **WHEN** no config file is provided and no environment variables are set
- **THEN** `MAX_ROUNDS` SHALL be 8, `MAX_REVIEW_CYCLES` SHALL be 3, `POLL_SECONDS` SHALL be 2, `MIN_REVIEW_CYCLES_BEFORE_APPROVAL` SHALL be 2, `REVIEW_EVIDENCE_MIN_MATCH` SHALL be 3

#### Scenario: Config file values apply when env vars absent
- **WHEN** a config file sets `limits.max_rounds` to 3 and `MAX_ROUNDS` env var is not set
- **THEN** `MAX_ROUNDS` SHALL be 3

#### Scenario: Default start agent is analyst
- **WHEN** no config file is provided and `START_AGENT` is not set
- **THEN** effective `START_AGENT` SHALL be `analyst`

#### Scenario: Post-processing defaults to disabled
- **WHEN** no config file is provided and `POST_OPENSPEC_ARCHIVE` / `POST_GIT_COMMIT` env vars are not set
- **THEN** `POST_OPENSPEC_ARCHIVE` SHALL be false and `POST_GIT_COMMIT` SHALL be false

#### Scenario: Post-processing enabled via env var
- **WHEN** `POST_OPENSPEC_ARCHIVE` env var is set to `1`
- **THEN** `POST_OPENSPEC_ARCHIVE` SHALL be true regardless of JSON config

### Requirement: API client with httpx
The orchestrator SHALL use an `ApiClient` class wrapping `httpx.Client` with methods: `create_session()`, `create_terminal()`, `send_input()`, `get_status()`, `get_last_output()`, `exit_terminal()`, `close()`. `create_session()` and `create_terminal()` SHALL accept a `provider` parameter instead of using a global.

#### Scenario: Create session with explicit provider
- **WHEN** `api.create_session("system_analyst", provider="claude_code")` is called
- **THEN** it SHALL POST to `/sessions` with `provider=claude_code`, `agent_profile=system_analyst`, and `working_directory` params

#### Scenario: Create terminal with explicit provider
- **WHEN** `api.create_terminal(session_name, "peer_system_analyst", provider="codex")` is called
- **THEN** it SHALL POST to `/sessions/{name}/terminals` with `provider=codex` and `agent_profile=peer_system_analyst`

#### Scenario: Send input to terminal
- **WHEN** `api.send_input(terminal_id, message)` is called
- **THEN** it SHALL POST to `/terminals/{id}/input` with the message param

### Requirement: Init and resume
`init_new_run()` SHALL create a session with 5 terminals, each using the provider and profile from `AGENT_CONFIG`. For fresh runs, the first dispatched role SHALL be `START_AGENT` exactly (`analyst`, `peer_analyst`, `programmer`, `peer_programmer`, or `tester`). On this first dispatch only, missing-upstream fallback checks SHALL be bypassed so the selected role is invoked first; when upstream output is unavailable, the prompt SHALL include an explicit placeholder note. After the first dispatch, existing phase/fallback behavior SHALL resume unchanged. After each terminal is created, the orchestrator SHALL send a rename command (`/rename {role}-{terminal_id}`) and wait up to 5 seconds for idle. Rename failure SHALL be logged and ignored. If terminal creation fails partway, the orchestrator SHALL call `exit_terminal()` for all already-created terminals before exiting with code 1. Resume mode SHALL load state from the state file and verify all terminal IDs are reachable via the API; persisted state phase remains authoritative during resume and `START_AGENT` is ignored.

#### Scenario: New run creates 5 terminals with per-agent providers
- **WHEN** `init_new_run()` is called with `AGENT_CONFIG` specifying mixed providers
- **THEN** it SHALL create each terminal with its configured provider and profile

#### Scenario: Fresh run starts from programmer role
- **WHEN** `START_AGENT` is `programmer` and run is not resuming
- **THEN** the first dispatched role SHALL be programmer

#### Scenario: Fresh run starts from peer analyst role
- **WHEN** `START_AGENT` is `peer_analyst` and run is not resuming
- **THEN** the first dispatched role SHALL be peer_analyst

#### Scenario: Fresh run starts from peer programmer role
- **WHEN** `START_AGENT` is `peer_programmer` and run is not resuming
- **THEN** the first dispatched role SHALL be peer_programmer

#### Scenario: Fresh run starts from tester role
- **WHEN** `START_AGENT` is `tester` and run is not resuming
- **THEN** the first dispatched role SHALL be tester

#### Scenario: First-dispatch peer analyst uses placeholder when upstream is missing
- **WHEN** `START_AGENT` is `peer_analyst` and `outputs["analyst"]` is empty on first dispatch
- **THEN** peer analyst prompt SHALL include an explicit placeholder note instead of triggering fallback to analyst

#### Scenario: First-dispatch peer programmer uses placeholder when upstream is missing
- **WHEN** `START_AGENT` is `peer_programmer` and `outputs["programmer"]` is empty on first dispatch
- **THEN** peer programmer prompt SHALL include an explicit placeholder note instead of triggering fallback to programmer

#### Scenario: Terminal renamed after creation
- **WHEN** a terminal with ID `da33cf00` is created for role `analyst`
- **THEN** the orchestrator SHALL send `/rename analyst-da33cf00` to that terminal

#### Scenario: Peer analyst terminal renamed with underscore format
- **WHEN** a terminal with ID `fae0481d` is created for role `peer_analyst`
- **THEN** the orchestrator SHALL send `/rename peer_analyst-fae0481d` to that terminal

#### Scenario: Rename failure is non-fatal
- **WHEN** the rename command fails or the terminal does not return to idle within 5 seconds
- **THEN** the orchestrator SHALL log a warning and continue

#### Scenario: Partial creation failure cleans up
- **WHEN** terminal creation fails on the 3rd terminal (programmer)
- **THEN** the orchestrator SHALL call `exit_terminal()` for analyst and peer_analyst terminals, then exit with code 1

#### Scenario: Resume with unreachable terminal fails
- **WHEN** `verify_resume_terminals()` is called and one terminal is unreachable
- **THEN** it SHALL exit with an error message

#### Scenario: Resume with provider mismatch logs warning
- **WHEN** `verify_resume_terminals()` is called and the state file has `analyst.provider` as `codex` but `AGENT_CONFIG["analyst"]["provider"]` is `claude_code`
- **THEN** the orchestrator SHALL log a warning identifying the mismatch and proceed with the run

#### Scenario: Resume ignores start agent override
- **WHEN** `RESUME=1`, state file has `current_phase: "tester"`, and `START_AGENT=analyst`
- **THEN** the orchestrator SHALL continue from `tester` phase from state

### Requirement: Prompt builders for all five agents
The orchestrator SHALL have prompt builder functions for analyst, analyst review, programmer, programmer review, and tester. Each SHALL include the appropriate explore block, guard lines, task instructions, and response file instruction.

On retry rounds (round > 1), `build_analyst_prompt()` SHALL instruct the analyst to first use the OpenSpec explore skill to investigate the test failure, then use the OpenSpec fast-forward skill to update artifacts. Note: the analyst is not invoked on retry rounds due to the shortened retry pipeline, but the prompt builder retains this behavior for correctness if called.

`build_programmer_prompt()` SHALL accept a `round_num` parameter. On round 1, the prompt SHALL include the analyst handoff as the upstream context. On retry rounds (`round_num > 1`), the prompt SHALL replace the analyst handoff with test failure feedback and previous changes context (see `shortcut-retry-pipeline` spec for details).

#### Scenario: Analyst prompt structure on round 1
- **WHEN** `build_analyst_prompt()` is called with `round_num=1`
- **THEN** the task instructions SHALL include "Explore the codebase" and "Create/update all OpenSpec artifacts using the OpenSpec fast-forward skill"

#### Scenario: Analyst prompt on retry round uses explore-then-ff
- **WHEN** `build_analyst_prompt()` is called with `round_num=2`
- **THEN** the task instructions SHALL include "Use the OpenSpec explore skill to investigate the test failure" followed by "use the OpenSpec fast-forward skill to update the artifacts"

#### Scenario: Programmer prompt condenses upstream on repeat
- **WHEN** `build_programmer_prompt()` is called with `round_num=1`, cycle > 1, and `CONDENSE_UPSTREAM_ON_REPEAT` is true
- **THEN** the analyst output SHALL be replaced with a back-reference

#### Scenario: Programmer prompt on retry round uses test failure context
- **WHEN** `build_programmer_prompt()` is called with `round_num=2`
- **THEN** the prompt SHALL contain test failure feedback instead of analyst handoff

### Requirement: State file with backward read-compatibility (Python only)
`save_state()` SHALL write JSON with `version: 1` and the same field structure as before: `updated_at`, `api`, `provider`, `wd`, `prompt`, `current_round`, `current_phase`, `final_status`, `session_name`, `terminals` (analyst, peer_analyst, programmer, peer_programmer, tester), `feedback`, `analyst_feedback`, `programmer_feedback`, `outputs` (analyst, analyst_review, programmer, programmer_review, tester).

The `terminals` section SHALL store each role as `{"id": terminal_id, "provider": provider_name}`. For backward read-compatibility, the Python orchestrator's `load_state()` SHALL accept the old format where `terminals.role` is a plain string (treated as `{"id": value, "provider": top_level_provider}`). The shell script orchestrator is NOT guaranteed to read the new format — this is a one-way upgrade for the Python orchestrator only.

#### Scenario: State roundtrip with per-agent providers
- **WHEN** state is saved with mixed providers and then loaded
- **THEN** all terminal IDs and provider values SHALL match the original values

#### Scenario: Loading old-format state file
- **WHEN** a state file has `terminals.analyst` as a plain string `"da33cf00"`
- **THEN** `load_state()` SHALL treat it as `{"id": "da33cf00", "provider": PROVIDER}`

#### Scenario: Invalid round in state file defaults to 1
- **WHEN** `current_round` in the state file is not a valid integer
- **THEN** `load_state()` SHALL default it to 1

#### Scenario: Invalid phase in state file defaults to analyst
- **WHEN** `current_phase` in the state file is not a valid phase name
- **THEN** `load_state()` SHALL default it to "analyst"
