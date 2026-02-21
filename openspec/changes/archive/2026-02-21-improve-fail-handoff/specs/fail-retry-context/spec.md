## ADDED Requirements

### Requirement: Condensed programmer summary carried on FAIL retry
On tester FAIL, the orchestrator SHALL save a condensed version of the programmer's output before clearing `outputs`. The condensed content SHALL be produced by `condense_programmer_for_tester()` (extracting "Files changed" and "Behavior implemented" sections, capped at `MAX_CROSS_PHASE_LINES`). This content SHALL be stored in a module-level global `programmer_context_for_retry`.

#### Scenario: FAIL sets programmer retry context
- **WHEN** the tester reports `RESULT: FAIL`
- **THEN** `programmer_context_for_retry` SHALL be set to `condense_programmer_for_tester(outputs["programmer"])` before `outputs` are cleared

#### Scenario: PASS does not set programmer retry context
- **WHEN** the tester reports `RESULT: PASS`
- **THEN** `programmer_context_for_retry` SHALL remain unchanged (the loop exits)

#### Scenario: Empty programmer output produces empty context
- **WHEN** the tester reports `RESULT: FAIL` and `outputs["programmer"]` is empty
- **THEN** `programmer_context_for_retry` SHALL be set to empty string

### Requirement: Programmer retry context persisted in state
The `save_state()` function SHALL include `programmer_context_for_retry` in the serialized JSON under the key `"programmer_context_for_retry"`. The `load_state()` function SHALL restore this field, defaulting to `""` if the key is absent (backward compatibility with old state files).

#### Scenario: State round-trip preserves retry context
- **WHEN** `programmer_context_for_retry` is `"- Files changed: foo.py\n- Behavior implemented: bar"` and `save_state()` is called, then globals are reset, then `load_state()` is called
- **THEN** `programmer_context_for_retry` SHALL equal `"- Files changed: foo.py\n- Behavior implemented: bar"`

#### Scenario: Loading old state file without retry context field
- **WHEN** `load_state()` reads a state file that has no `"programmer_context_for_retry"` key
- **THEN** `programmer_context_for_retry` SHALL be set to `""`

### Requirement: Analyst prompt includes programmer context on retry rounds
The `build_analyst_prompt()` function SHALL include `programmer_context_for_retry` in the analyst prompt when `round_num > 1` and `programmer_context_for_retry` is non-empty. The block SHALL appear after "Latest tester feedback:" and before "Latest peer analyst feedback:". The block SHALL be labeled "Previous round programmer changes (context only):".

#### Scenario: Round 2 analyst prompt includes programmer context
- **WHEN** `round_num` is 2 and `programmer_context_for_retry` is `"- Files changed: foo.py"`
- **THEN** the analyst prompt SHALL contain `"Previous round programmer changes (context only):\n- Files changed: foo.py"`

#### Scenario: Round 1 analyst prompt excludes programmer context
- **WHEN** `round_num` is 1
- **THEN** the analyst prompt SHALL NOT contain "Previous round programmer changes"

#### Scenario: Round 2 with empty programmer context excludes block
- **WHEN** `round_num` is 2 and `programmer_context_for_retry` is `""`
- **THEN** the analyst prompt SHALL NOT contain "Previous round programmer changes"

### Requirement: Other agent prompts never include programmer retry context
The `build_programmer_prompt()`, `build_programmer_review_prompt()`, `build_analyst_review_prompt()`, and `build_tester_prompt()` functions SHALL NOT reference `programmer_context_for_retry`.

#### Scenario: Programmer prompt has no retry context
- **WHEN** `programmer_context_for_retry` is non-empty
- **THEN** the output of `build_programmer_prompt()` SHALL NOT contain "Previous round programmer changes"

#### Scenario: Tester prompt has no retry context
- **WHEN** `programmer_context_for_retry` is non-empty
- **THEN** the output of `build_tester_prompt()` SHALL NOT contain "Previous round programmer changes"
