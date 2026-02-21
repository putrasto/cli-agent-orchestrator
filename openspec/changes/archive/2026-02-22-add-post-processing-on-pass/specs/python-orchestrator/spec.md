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
