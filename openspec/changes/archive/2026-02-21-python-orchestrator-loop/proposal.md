## Why

The current shell-based orchestrator (`run_orchestrator_loop.sh`) parses raw terminal output to extract agent responses — stripping ANSI codes, searching regex markers, handling stability polls. This is fragile and burns tokens by re-parsing bloated terminal history. A Python replacement using file-based handoff eliminates this by having each agent write its response to a file, which the orchestrator reads directly.

## What Changes

- New Python orchestrator script (`examples/codex-3agents/run_orchestrator_loop.py`) that replaces the shell script's output extraction with file-based agent handoff
- Each agent prompt gets a `RESPONSE FILE INSTRUCTION` block telling it to write its final response to a specific file under `.tmp/agent-responses/`
- Orchestrator polls for file existence + terminal idle status, reads the file, deletes it, and passes content to the next agent
- Graceful fallback to `api.get_last_output()` if the agent ignores the file instruction
- Removes need for `HANDOFF_STABLE_POLLS`, `get_structured_output`, and ANSI stripping
- Uses `httpx` (sync) instead of `curl` + `jq` for API calls
- Same 5-agent flow, approval gates, evidence validation, state management, and env var interface as the shell script
- State file JSON format is byte-compatible for cross-tool resume
- Unit test suite covering all pure functions (43 tests)

## Capabilities

### New Capabilities
- `file-based-handoff`: Agent response handoff via filesystem — polling, reading, cleanup, fallback, and response file instruction injection
- `python-orchestrator`: Python orchestration loop with httpx API client, state management, prompt builders, review gates, and feedback condensation

### Modified Capabilities

## Impact

- New file: `examples/codex-3agents/run_orchestrator_loop.py` (~550 lines)
- New file: `test/examples/test_orchestrator_loop_unit.py` (43 unit tests)
- New file: `test/examples/__init__.py`
- Runtime dependency: `httpx` (not currently in project dependencies — used only by the example script, not by the main package)
- No changes to agent profiles, API server, or existing shell script
- No changes to the main `src/` package
