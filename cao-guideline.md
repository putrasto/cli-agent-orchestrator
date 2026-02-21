CAO Orchestrator Guideline (3-Agent Loop)

Goal
- Run one orchestration flow from a single human prompt.
- Use 5 dedicated agents: `system_analyst`, `peer_system_analyst`, `programmer`, `peer_programmer`, `tester`.
- Automatically retry the same flow until tests pass.
- Use a structured prompt with two sections:
  - `*** ORIGINAL EXPLORE SUMMARY ***`
  - `*** SCENARIO TEST ***`

Roles
- `system_analyst`
  - Explore the codebase and requirements.
  - Use OpenSpec to create/update all required OpenSpec artifacts.
  - Use the OpenSpec fast-forward skill as the standard execution method for exploration/artifact creation.
  - Guard line: `system anaylist: dont do testing, dont implement code`
- `programmer`
  - Apply implementation changes from OpenSpec artifacts.
  - Use `openspec-apply-change` skill.
  - Produce code changes only (no test pass/fail decision).
  - Guard line: `programmer: dont do scenario test`
- `peer_system_analyst`
  - Review `system_analyst` output before programmer starts.
  - Must return `REVIEW_RESULT: APPROVED|REVISE`.
- `peer_programmer`
  - Review `programmer` output before tester starts.
  - Must return `REVIEW_RESULT: APPROVED|REVISE`.
- `tester`
  - Execute tests based on `*** SCENARIO TEST ***`.
  - Validate behavior and acceptance criteria from the scenario section.
  - Return structured test result: `PASS` or `FAIL` with evidence.
  - Guard line: `tester: dont implement code, dont modify openspec artifact`

Human Interaction Rule
- Human provides one prompt only at start.
- No additional human input is required during retry cycles.
- Orchestrator owns all retries and routing.

Orchestration Flow
1. Receive one human prompt.
2. Parse prompt into:
   - `ORIGINAL EXPLORE SUMMARY` section
   - `SCENARIO TEST` section
3. Send only `ORIGINAL EXPLORE SUMMARY` to `system_analyst`.
4. `peer_system_analyst` reviews analyst output.
5. If review is `REVISE`, analyst reworks and peer re-reviews (up to `MAX_REVIEW_CYCLES`).
6. Send approved analyst output to `programmer`.
7. `peer_programmer` reviews programmer output.
8. If review is `REVISE`, programmer reworks and peer re-reviews (up to `MAX_REVIEW_CYCLES`).
9. Send only `SCENARIO TEST` + approved programmer output to `tester`.
10. `tester` runs test plan and reports `PASS` or `FAIL`.
11. Orchestrator evaluates result:
   - If `PASS`: finish and return final result.
   - If `FAIL`: restart from step 3 using failure feedback, then repeat until `PASS`.

Retry Policy
- Retry with same five-agent sequence only.
- Keep the original prompt fixed as source-of-truth.
- Include latest failure report in next `system_analyst` handoff.
- Continue loop until `tester` reports `PASS`.
- Peer review retries are controlled by `MAX_REVIEW_CYCLES`.

Minimum Data Passed Between Agents
- `ORIGINAL EXPLORE SUMMARY` for analyst/programmer.
- `SCENARIO TEST` for tester.
- Current OpenSpec artifacts and implementation summary.
- Latest test report (for retries).
- Latest peer review notes (for analyst/programmer rework cycles).

Prompt Template
```text
*** ORIGINAL EXPLORE SUMMARY ***
<requirements and context for analysis/design>

*** SCENARIO TEST ***
<acceptance tests and validation scenarios>
```

Recommended detailed template:
- `examples/agnostic-3agents/prompt_template.md`
- Use your OpenSpec explore findings as the `ORIGINAL EXPLORE SUMMARY`.
- Use real input data + exact expected result in `SCENARIO TEST`.

Completion Criteria
- Orchestrator stops only when tester result is `PASS`.
- Final output to human includes:
  - brief change summary
  - test evidence
  - pass confirmation

Copy-Paste Commands

1) Start CAO server (terminal A)
```bash
cd ~/project/cli-agent-orchestrator
CAO_ENABLE_WORKING_DIRECTORY=true cao-server
```

2) Install the 3 agent profiles (terminal B)
```bash
cd ~/project/cli-agent-orchestrator
cao install examples/agnostic-3agents/system_analyst.md --provider codex
cao install examples/agnostic-3agents/peer_system_analyst.md --provider codex
cao install examples/agnostic-3agents/programmer.md --provider codex
cao install examples/agnostic-3agents/peer_programmer.md --provider codex
cao install examples/agnostic-3agents/tester.md --provider codex
```

3) Run one-prompt orchestrator loop (terminal B)
```bash
cd ~/project/cli-agent-orchestrator
PROMPT_FILE="$PWD/path/to/your_prompt.txt" \
WD="$PWD" \
MAX_ROUNDS=8 \
MAX_REVIEW_CYCLES=3 \
python examples/agnostic-3agents/run_orchestrator_loop.py
```

Optional: inline `PROMPT` still works if needed.

Notes
- This loop keeps human input to one prompt only.
- The orchestrator decides pass/fail from tester output and retries automatically.
- You can tune retries by setting `MAX_ROUNDS` before running the block.
- You can tune peer review retries by setting `MAX_REVIEW_CYCLES`.
