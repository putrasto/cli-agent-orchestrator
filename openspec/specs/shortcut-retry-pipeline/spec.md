### Requirement: Shortened retry pipeline on tester FAIL
When the tester reports `RESULT: FAIL`, the orchestrator SHALL set `current_phase = PHASE_PROGRAMMER` (not `PHASE_ANALYST`) before incrementing `current_round`. This causes retry rounds to execute the shortened pipeline: programmer → peer_programmer → tester, skipping analyst and peer_analyst entirely.

This behavior SHALL be always-on with no configuration flag. There SHALL be no automatic escalation back to the analyst phase after any number of consecutive FAIL rounds.

#### Scenario: FAIL sets phase to PROGRAMMER for next round
- **WHEN** the tester reports `RESULT: FAIL`
- **THEN** `current_phase` SHALL be set to `PHASE_PROGRAMMER` before `current_round` is incremented

#### Scenario: Retry round skips analyst and peer_analyst
- **WHEN** `current_round` is 2 and `current_phase` is `PHASE_PROGRAMMER`
- **THEN** the main loop SHALL NOT execute the `PHASE_ANALYST` block, and SHALL proceed directly to the `PHASE_PROGRAMMER` block

#### Scenario: Round 1 still uses full pipeline
- **WHEN** `current_round` is 1 and `current_phase` is `PHASE_ANALYST`
- **THEN** the main loop SHALL execute analyst → peer_analyst → programmer → peer_programmer → tester

#### Scenario: Multiple consecutive FAILs stay on short pipeline
- **WHEN** the tester reports `RESULT: FAIL` on rounds 2 and 3
- **THEN** both round 3 and round 4 SHALL start at `PHASE_PROGRAMMER`, never reverting to `PHASE_ANALYST`

### Requirement: Selective output clearing on FAIL
On tester FAIL, the orchestrator SHALL clear only `outputs["programmer"]`, `outputs["programmer_review"]`, and `outputs["tester"]`. The orchestrator SHALL preserve `outputs["analyst"]` and `outputs["analyst_review"]` from the last analyst pass.

The preserved analyst outputs are for state file consistency and debugging. They SHALL NOT be used in retry round prompts — artifacts on disk are the source of truth.

#### Scenario: FAIL clears programmer and tester outputs
- **WHEN** the tester reports `RESULT: FAIL`
- **THEN** `outputs["programmer"]`, `outputs["programmer_review"]`, and `outputs["tester"]` SHALL be set to `""`

#### Scenario: FAIL preserves analyst outputs
- **WHEN** the tester reports `RESULT: FAIL` and `outputs["analyst"]` is `"analyst summary text"`
- **THEN** `outputs["analyst"]` SHALL remain `"analyst summary text"` after the FAIL handler completes

#### Scenario: FAIL preserves analyst review output
- **WHEN** the tester reports `RESULT: FAIL` and `outputs["analyst_review"]` is `"review text"`
- **THEN** `outputs["analyst_review"]` SHALL remain `"review text"` after the FAIL handler completes

### Requirement: Programmer retry prompt with test failure context
On retry rounds (`round_num > 1`), `build_programmer_prompt()` SHALL construct a different prompt than on round 1:

- The "System analyst handoff" block SHALL be replaced with a "Test failure feedback" block containing the condensed test evidence from the `feedback` global.
- The prompt SHALL include `programmer_context_for_retry` as "Your previous changes (context):" when non-empty.
- The prompt SHALL instruct the programmer to use `/opsx:explore` to investigate the failure and `/opsx:ff` to update OpenSpec artifacts if needed.
- The prompt SHALL explicitly state that the programmer may update OpenSpec artifacts if the failure indicates a spec/design issue.
- The prompt SHALL NOT include `outputs["analyst"]`.

On round 1, the prompt SHALL remain unchanged (includes analyst handoff as today).

#### Scenario: Retry programmer prompt includes test failure feedback
- **WHEN** `build_programmer_prompt()` is called with `round_num=2` and `feedback` is `"RESULT: FAIL\nEVIDENCE:\n- test_foo failed"`
- **THEN** the prompt SHALL contain `"Test failure feedback:"` followed by the feedback content

#### Scenario: Retry programmer prompt excludes analyst output
- **WHEN** `build_programmer_prompt()` is called with `round_num=2`
- **THEN** the prompt SHALL NOT contain `"System analyst handoff:"`

#### Scenario: Retry programmer prompt includes previous changes context
- **WHEN** `build_programmer_prompt()` is called with `round_num=2` and `programmer_context_for_retry` is `"- Files changed: foo.py"`
- **THEN** the prompt SHALL contain `"Your previous changes (context):"` followed by the context

#### Scenario: Retry programmer prompt with empty previous changes omits block
- **WHEN** `build_programmer_prompt()` is called with `round_num=2` and `programmer_context_for_retry` is `""`
- **THEN** the prompt SHALL NOT contain `"Your previous changes (context):"`

#### Scenario: Retry programmer prompt instructs artifact update capability
- **WHEN** `build_programmer_prompt()` is called with `round_num=2`
- **THEN** the prompt SHALL contain instructions to investigate the failure and update OpenSpec artifacts if needed

#### Scenario: Round 1 programmer prompt unchanged
- **WHEN** `build_programmer_prompt()` is called with `round_num=1`
- **THEN** the prompt SHALL contain `"System analyst handoff:"` and SHALL NOT contain `"Test failure feedback:"`

### Requirement: Shortcut retry works with non-analyst START_AGENT
When `START_AGENT` is `programmer`, `peer_programmer`, or `tester` and no real analyst pass occurred, `outputs["analyst"]` SHALL contain the `_UPSTREAM_PLACEHOLDER`. The shortened retry pipeline SHALL still apply — the programmer works from artifacts on disk and test failure feedback, not from analyst output.

#### Scenario: START_AGENT=programmer with FAIL uses short retry
- **WHEN** `START_AGENT` is `programmer`, round 1 completes with tester FAIL, and `outputs["analyst"]` is `_UPSTREAM_PLACEHOLDER`
- **THEN** round 2 SHALL set `current_phase = PHASE_PROGRAMMER` and the programmer prompt SHALL contain `"Test failure feedback:"`, not `"System analyst handoff:"`

#### Scenario: Resume in retry state preserves short pipeline
- **WHEN** state file has `current_round: 2`, `current_phase: "programmer"`, and `outputs["analyst"]` is non-empty (preserved from round 1)
- **THEN** the orchestrator SHALL resume at the programmer phase without falling back to analyst

#### Scenario: Resume in retry state with empty analyst output falls back to analyst
- **WHEN** state file has `current_round: 2`, `current_phase: "programmer"`, and `outputs["analyst"]` is empty (e.g., old state file format)
- **THEN** the existing guard at the programmer phase SHALL fall back to `PHASE_ANALYST` for that round (existing behavior, unchanged)
