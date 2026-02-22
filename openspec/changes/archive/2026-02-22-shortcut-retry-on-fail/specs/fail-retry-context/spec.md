## MODIFIED Requirements

### Requirement: Condensed programmer summary carried on FAIL retry
On tester FAIL, the orchestrator SHALL save a condensed version of the programmer's output before clearing programmer/tester outputs. The condensed content SHALL be produced by `condense_programmer_for_tester()` (extracting "Files changed" and "Behavior implemented" sections, capped at `MAX_CROSS_PHASE_LINES`). This content SHALL be stored in a module-level global `programmer_context_for_retry`.

#### Scenario: FAIL sets programmer retry context
- **WHEN** the tester reports `RESULT: FAIL`
- **THEN** `programmer_context_for_retry` SHALL be set to `condense_programmer_for_tester(outputs["programmer"])` before programmer/tester outputs are cleared

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

### Requirement: Programmer prompt includes retry context on retry rounds
The `build_programmer_prompt()` function SHALL include `programmer_context_for_retry` in the programmer prompt when `round_num > 1` and `programmer_context_for_retry` is non-empty. The block SHALL be labeled "Your previous changes (context):".

#### Scenario: Retry programmer prompt includes previous changes
- **WHEN** `round_num` is 2 and `programmer_context_for_retry` is `"- Files changed: foo.py"`
- **THEN** the programmer prompt SHALL contain `"Your previous changes (context):\n- Files changed: foo.py"`

#### Scenario: Round 1 programmer prompt excludes retry context
- **WHEN** `round_num` is 1
- **THEN** the programmer prompt SHALL NOT contain "Your previous changes"

#### Scenario: Retry with empty programmer context excludes block
- **WHEN** `round_num` is 2 and `programmer_context_for_retry` is `""`
- **THEN** the programmer prompt SHALL NOT contain "Your previous changes"

### Requirement: Non-programmer prompts exclude retry context
`build_programmer_review_prompt()`, `build_analyst_review_prompt()`, `build_tester_prompt()`, and `build_analyst_prompt()` SHALL NOT reference `programmer_context_for_retry`. Only `build_programmer_prompt()` SHALL include it (on retry rounds).

#### Scenario: Tester prompt has no retry context
- **WHEN** `programmer_context_for_retry` is non-empty
- **THEN** the output of `build_tester_prompt()` SHALL NOT contain "Your previous changes" or "Previous round programmer changes"

#### Scenario: Programmer review prompt has no retry context
- **WHEN** `programmer_context_for_retry` is non-empty
- **THEN** the output of `build_programmer_review_prompt()` SHALL NOT contain "Your previous changes" or "Previous round programmer changes"

#### Scenario: Analyst review prompt has no retry context
- **WHEN** `programmer_context_for_retry` is non-empty
- **THEN** the output of `build_analyst_review_prompt()` SHALL NOT contain "Your previous changes" or "Previous round programmer changes"

## REMOVED Requirements

### Requirement: Analyst prompt includes programmer context on retry rounds
**Reason**: The analyst is no longer invoked on retry rounds due to the shortened retry pipeline. The programmer receives the retry context directly instead.
**Migration**: `programmer_context_for_retry` is now included in `build_programmer_prompt()` on retry rounds (see modified requirement "Programmer prompt includes retry context on retry rounds" above).

### Requirement: Other agent prompts never include programmer retry context
**Reason**: Replaced by modified requirement "Non-programmer prompts exclude retry context" above, which narrows the scope — `build_programmer_prompt()` now includes retry context on retry rounds, while all other prompt builders remain excluded.
**Migration**: No code migration needed. The exclusion still applies to all non-programmer prompts.
