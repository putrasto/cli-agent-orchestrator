## MODIFIED Requirements

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
