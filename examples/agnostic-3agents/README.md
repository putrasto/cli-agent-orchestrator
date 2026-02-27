# 3-Agent Orchestrator Loop

A Python orchestrator that coordinates 5 AI agent terminals (analyst, peer analyst, programmer, peer programmer, tester) through a structured development loop. Uses **file-based handoff** — each agent writes its response to a file, the orchestrator reads it, archives it, and passes condensed content to the next agent. The orchestrator itself uses **zero LLM tokens**.

## Prerequisites

- CAO server installed and working (`uv sync` from project root)
- An AI CLI agent installed and available in `$PATH` (Claude Code, Codex, Q CLI, or Kiro CLI)
- A prompt file following the required template (see `prompt_template.md`)

## 1. Start the CAO server

```bash
cao-server
```

The server runs on `http://localhost:9889` by default. Verify it's running:

```bash
curl -s http://localhost:9889/health
```

## 2. Create a prompt file

Copy the template and fill in your task details:

```bash
cp prompt_template.md my_prompt.md
# Edit my_prompt.md with your task
```

The prompt **must** contain both headers:
- `*** ORIGINAL EXPLORE SUMMARY ***` — describes the business goal, scope, constraints
- `*** SCENARIO TEST ***` — defines the test scenario with exact inputs, steps, and expected results

## 3. Run the orchestrator loop

The orchestrator runs **against a target project**, not from within it. You can configure it via a JSON config file (recommended) or environment variables.

### Using a JSON config file (recommended)

```bash
uv run python examples/agnostic-3agents/run_orchestrator_loop.py config-fresh.json
```

See sample config files in this directory:
- `config-fresh.json` — starter config with mixed providers (e.g., Claude Code for analyst, Codex for peers)
- `config-incremental.json` — starter config for incremental changes on existing projects (incremental behavior is driven by the prompt file content, not a config flag)
- `config-resume.json` — minimal config for resuming an interrupted run

### Using environment variables (backward compatible)

```bash
PROMPT_FILE="/path/to/your/project/.tmp/prompt.txt" \
WD="/path/to/your/project" \
  uv run python examples/agnostic-3agents/run_orchestrator_loop.py
```

Full recommended invocation with token-efficient settings:

```bash
PROMPT_FILE="/path/to/your/project/.tmp/prompt.txt" \
WD="/path/to/your/project" \
PROJECT_TEST_CMD="pytest -q" \
MAX_ROUNDS=3 \
MAX_REVIEW_CYCLES=2 \
MIN_REVIEW_CYCLES_BEFORE_APPROVAL=1 \
CLEANUP_ON_EXIT=1 \
  uv run python examples/agnostic-3agents/run_orchestrator_loop.py
```

### Config precedence

Environment variables > JSON config file > hardcoded defaults. Empty env vars are treated as unset.

- `WD` — the project the agents will explore, modify, and test. Response files and state are written under `WD/.tmp/`.
- `PROMPT_FILE` — absolute path to the prompt file (can live anywhere, but keeping it in `WD/.tmp/` is convenient).
- `PROJECT_TEST_CMD` — the command the peer programmer runs to validate the implementation.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Tester returned PASS |
| 1 | All rounds exhausted without PASS, or fatal error |
| 130 | Interrupted by SIGINT (Ctrl+C) |
| 143 | Interrupted by SIGTERM |

## Environment variables

### Required

| Variable | Description |
|----------|-------------|
| `WD` | **Target project directory** — the codebase agents will work on. Response files, state, and agent outputs are written under `WD/.tmp/`. Defaults to current directory if not set. |
| `PROMPT_FILE` | Absolute path to prompt file (or set `PROMPT` inline) |

### Common overrides

| Variable | Default | Description |
|----------|---------|-------------|
| `API` | `http://localhost:9889` | CAO server URL |
| `PROVIDER` | `codex` | AI provider (`codex`, `claude_code`, `q_cli`, `kiro_cli`) |
| `MAX_ROUNDS` | `8` | Max analyst-programmer-tester loops (recommended: `3`) |
| `MAX_REVIEW_CYCLES` | `3` | Max peer review cycles per phase (recommended: `2`) |
| `MIN_REVIEW_CYCLES_BEFORE_APPROVAL` | `2` | Min cycles before peer can approve (recommended: `1`) |
| `PROJECT_TEST_CMD` | (empty) | Test command for programmer reviewer to run |
| `START_AGENT` | `analyst` | Start orchestration from this agent (`analyst`, `peer_analyst`, `programmer`, `peer_programmer`, `tester`). Ignored on resume. |
| `CLEANUP_ON_EXIT` | `0` | Set `1` to exit all terminals on completion |

### Handoff and token control

| Variable | Default | Description |
|----------|---------|-------------|
| `CONDENSE_CROSS_PHASE` | `1` | Extract only handoff sections when passing between phases |
| `MAX_CROSS_PHASE_LINES` | `40` | Max lines in cross-phase condensed output |
| `CONDENSE_UPSTREAM_ON_REPEAT` | `1` | Replace analyst output with back-reference on programmer cycle > 1 |
| `CONDENSE_EXPLORE_ON_REPEAT` | `1` | Replace explore summary with back-reference on repeat sends |
| `CONDENSE_REVIEW_FEEDBACK` | `1` | Extract only REVIEW_NOTES section from peer reviews |
| `MAX_FEEDBACK_LINES` | `30` | Max lines in condensed feedback |
| `AUTO_ACCEPT_PERMISSIONS` | `0` | Set `1` to auto-accept provider permission prompts (`waiting_user_answer`) by sending `y`; default off |
| `STRICT_FILE_HANDOFF` | `1` | Fail if agent doesn't write response file (set `0` to fall back to terminal output) |
| `IDLE_GRACE_SECONDS` | `30` | Dual role: (1) startup guard timeout — max seconds to wait for agent to enter processing state after dispatch; (2) idle grace — seconds of continuous idle before giving up on response file |
| `MAX_FILE_REMINDERS` | `1` | Number of reminder messages to send when agent goes idle without writing response file, before failing or falling back |
| `RESPONSE_TIMEOUT` | `1800` | Max seconds to wait for agent to finish (while still processing) |

### Resume control

| Variable | Default | Description |
|----------|---------|-------------|
| `RESUME` | `0` | Set `1` to force resume from state file |
| `STATE_FILE` | `.tmp/agnostic-3agents-loop-state.json` | Path to state file |

Auto-resume: if a state file exists with `final_status=RUNNING`, the orchestrator resumes automatically without needing `RESUME=1`.
On terminal completion (`PASS` or max-round `FAIL`), the canonical state file is moved to `.tmp/<run-timestamp>/agnostic-3agents-loop-state.json`.

## Scenarios

### Quick single-round test

```bash
WD=/path/to/project \
PROMPT_FILE=/path/to/project/.tmp/prompt.txt \
MAX_ROUNDS=1 MAX_REVIEW_CYCLES=1 \
  uv run python examples/agnostic-3agents/run_orchestrator_loop.py
```

### With explicit test command

```bash
WD=/path/to/project \
PROMPT_FILE=/path/to/project/.tmp/prompt.txt \
PROJECT_TEST_CMD="conda run -n myenv pytest -q" \
  uv run python examples/agnostic-3agents/run_orchestrator_loop.py
```

The test command is included in the programmer review prompt so the peer reviewer runs it before approving. Use the full command including any environment activation (e.g. `conda run`, `poetry run`).

### Resume after interruption

If the orchestrator is interrupted (Ctrl+C), it saves state automatically. On next run it resumes from where it left off:

```bash
# First run — gets interrupted
uv run python examples/agnostic-3agents/run_orchestrator_loop.py config-fresh.json
# ^C

# Resume using the resume config
uv run python examples/agnostic-3agents/run_orchestrator_loop.py config-resume.json

# Or resumes automatically (state file has RUNNING status)
uv run python examples/agnostic-3agents/run_orchestrator_loop.py config-fresh.json
```

To force a fresh start after interruption:

```bash
rm /path/to/project/.tmp/agnostic-3agents-loop-state.json
```

### Non-strict mode (fallback to terminal output)

If your AI provider doesn't reliably write response files, disable strict mode:

```bash
WD=/path/to/project \
PROMPT_FILE=/path/to/project/.tmp/prompt.txt \
STRICT_FILE_HANDOFF=0 \
  uv run python examples/agnostic-3agents/run_orchestrator_loop.py
```

This falls back to reading terminal output when the response file doesn't appear. Costs more tokens but is more tolerant.

### Auto-accept permission prompts (optional)

If your provider returns `waiting_user_answer` for runtime permission dialogs (for example Claude Code sandbox-escape confirmations), you can opt in to auto-accept:

```bash
WD=/path/to/project \
PROMPT_FILE=/path/to/project/.tmp/prompt.txt \
AUTO_ACCEPT_PERMISSIONS=1 \
  uv run python examples/agnostic-3agents/run_orchestrator_loop.py
```

Default is `AUTO_ACCEPT_PERMISSIONS=0` (off).

### Cleanup terminals on exit

By default, terminals persist in tmux after the orchestrator exits — useful for debugging (you can inspect what each agent did by attaching to the tmux session). Set `CLEANUP_ON_EXIT=1` to exit all terminals on completion.

## How it works

```text
Round 1:
  Analyst -> Peer Analyst (review cycles)
  Programmer -> Peer Programmer (review cycles)
  Tester -> PASS: exit 0 / FAIL: retry

Retry rounds (after FAIL):
  Programmer -> Peer Programmer (review cycles)
  Tester -> PASS: exit 0 / FAIL: next retry
```

1. **Analyst** (round 1) receives the explore summary and scenario test. Produces an `ANALYST_SUMMARY` with scope, artifacts, implementation notes, and risks.

2. **Peer Analyst** reviews the analyst output against a checklist. Returns `REVIEW_RESULT: APPROVED` or `REVIEW_RESULT: REVISE` with notes. Cycles until approved or `MAX_REVIEW_CYCLES` reached.

3. **Programmer** receives condensed analyst handoff (implementation notes + risks only). Implements the changes. Produces a `PROGRAMMER_SUMMARY` with files changed and behavior implemented.

4. **Peer Programmer** reviews the implementation with full programmer output. Optionally runs `PROJECT_TEST_CMD`. Cycles until approved or `MAX_REVIEW_CYCLES` reached.

5. **Tester** receives condensed programmer handoff (files changed + behavior only). Runs the scenario test. Returns `RESULT: PASS` or `RESULT: FAIL` with evidence.
6. **On FAIL**, the orchestrator retries from **Programmer** (shortened retry pipeline) and carries condensed test evidence forward.

### File-based handoff

Each agent prompt includes a `RESPONSE FILE INSTRUCTION` block telling the agent to write its final response to a specific file under `.tmp/agent-responses/`:

| Agent | Response file |
|-------|---------------|
| Analyst | `analyst_summary.md` |
| Peer Analyst | `analyst_review.md` |
| Programmer | `programmer_summary.md` |
| Peer Programmer | `programmer_review.md` |
| Tester | `test_result.md` |

The orchestrator polls: file exists AND terminal idle/completed -> read, archive under `.tmp/<run-timestamp>/`, proceed.

## Agent profiles

The agent profiles (`.md` files in this directory) define each agent's system prompt:

| File | Role |
|------|------|
| `system_analyst.md` | Analyst — explores codebase, creates OpenSpec artifacts |
| `peer_system_analyst.md` | Peer Analyst — reviews analyst work against checklist |
| `programmer.md` | Programmer — implements changes via OpenSpec apply |
| `peer_programmer.md` | Peer Programmer — reviews implementation, runs tests |
| `tester.md` | Tester — runs scenario test, reports PASS/FAIL |
