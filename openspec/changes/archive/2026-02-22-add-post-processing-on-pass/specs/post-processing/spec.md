## ADDED Requirements

### Requirement: Active change detection
The orchestrator SHALL detect the active OpenSpec change by listing non-`archive` subdirectories under `openspec/changes/` relative to `WD`. If exactly one active change exists, it SHALL be used. If zero or multiple active changes exist, the step SHALL be skipped with a log warning.

#### Scenario: Exactly one active change
- **WHEN** `openspec/changes/` contains one directory `fix-auth` (and optionally `archive/`)
- **THEN** the detected change name SHALL be `fix-auth`

#### Scenario: No active changes
- **WHEN** `openspec/changes/` contains only `archive/` or is empty
- **THEN** the archive step SHALL be skipped with a log warning "No active OpenSpec change found, skipping archive"

#### Scenario: Multiple active changes
- **WHEN** `openspec/changes/` contains `fix-auth` and `add-feature` (excluding `archive/`)
- **THEN** the archive step SHALL be skipped with a log warning "Multiple active OpenSpec changes found (fix-auth, add-feature), skipping archive"

#### Scenario: No openspec/changes directory
- **WHEN** `openspec/changes/` does not exist under `WD`
- **THEN** the archive step SHALL be skipped with a log warning

### Requirement: OpenSpec archive step
When `POST_OPENSPEC_ARCHIVE` is enabled and an active change is detected, the orchestrator SHALL run `openspec archive <name> --yes` as a subprocess with `cwd=WD`. The step SHALL capture stdout/stderr and log the result.

#### Scenario: Archive succeeds
- **WHEN** `openspec archive fix-auth --yes` exits with code 0
- **THEN** the orchestrator SHALL log success and proceed to the git commit step

#### Scenario: Archive fails
- **WHEN** `openspec archive fix-auth --yes` exits with a non-zero code
- **THEN** the orchestrator SHALL log the error (including stderr) and skip the git commit step (when both are enabled)

#### Scenario: Archive skipped because disabled
- **WHEN** `POST_OPENSPEC_ARCHIVE` is false
- **THEN** the archive step SHALL not run

### Requirement: Git commit step
When `POST_GIT_COMMIT` is enabled, the orchestrator SHALL run git commands as subprocesses with `cwd=WD` in this order:
1. Check if `WD` is a git repo (`git rev-parse --git-dir`)
2. Stage all changes (`git add -A`)
3. Check for staged changes (`git diff --cached --quiet`)
4. Commit with a standard message (`git commit -m "..."`)

#### Scenario: Git commit succeeds
- **WHEN** `WD` is a git repo, there are staged changes, and commit succeeds
- **THEN** the orchestrator SHALL log the commit hash and continue to exit

#### Scenario: No staged changes after git add
- **WHEN** `git diff --cached --quiet` exits with code 0 (no changes)
- **THEN** the orchestrator SHALL skip the commit with a log message "No changes to commit"

#### Scenario: Not a git repo
- **WHEN** `git rev-parse --git-dir` fails
- **THEN** the git step SHALL be skipped with a log warning "Not a git repo, skipping commit"

#### Scenario: Git commit fails
- **WHEN** `git commit` exits with a non-zero code
- **THEN** the orchestrator SHALL log the error and continue to exit

#### Scenario: Git commit skipped because disabled
- **WHEN** `POST_GIT_COMMIT` is false
- **THEN** the git step SHALL not run

#### Scenario: Git commit skipped because archive failed
- **WHEN** both `POST_OPENSPEC_ARCHIVE` and `POST_GIT_COMMIT` are enabled and the archive step failed (non-zero exit)
- **THEN** the git commit step SHALL be skipped with a log message "Skipping git commit because OpenSpec archive failed"

#### Scenario: Git commit proceeds when archive was skipped
- **WHEN** both `POST_OPENSPEC_ARCHIVE` and `POST_GIT_COMMIT` are enabled and the archive step was skipped (no active change or multiple changes)
- **THEN** the git commit step SHALL still run (skipped ≠ failed)

### Requirement: Post-processing execution order
The orchestrator SHALL run post-processing steps after `save_state()` with `final_status="PASS"` and before `cleanup()`. Steps SHALL run in order: OpenSpec archive first, then git commit. If both steps are disabled (default), the PASS branch SHALL behave identically to the current implementation.

#### Scenario: Both steps enabled and succeed
- **WHEN** `POST_OPENSPEC_ARCHIVE` and `POST_GIT_COMMIT` are both true, archive succeeds, and commit succeeds
- **THEN** both steps SHALL run in order and the orchestrator SHALL exit with code 0

#### Scenario: Both steps disabled (default)
- **WHEN** `POST_OPENSPEC_ARCHIVE` and `POST_GIT_COMMIT` are both false
- **THEN** no post-processing SHALL run and the PASS branch SHALL go directly to cleanup and exit

#### Scenario: Post-processing failure does not change exit code
- **WHEN** any post-processing step fails
- **THEN** the orchestrator SHALL still exit with code 0 (PASS result is authoritative)
