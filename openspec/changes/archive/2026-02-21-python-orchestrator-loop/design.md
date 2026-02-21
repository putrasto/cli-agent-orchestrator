## Context

The 3-agent orchestrator loop (`examples/codex-3agents/`) drives 5 agent terminals through an analyst → peer review → programmer → peer review → tester cycle. The current shell implementation (`run_orchestrator_loop.sh`) extracts agent responses by fetching full terminal output, stripping ANSI escape codes, and regex-searching for marker lines like `ANALYST_SUMMARY` or `REVIEW_RESULT`. This requires `HANDOFF_STABLE_POLLS` to avoid reading stale output and `get_structured_output` with line-by-line stop conditions for Codex UI artifacts.

The Python replacement operates at the file layer: each agent is instructed to write its response to a known path, and the orchestrator polls for that file.

## Goals / Non-Goals

**Goals:**
- Eliminate ANSI stripping and regex-based output extraction from the orchestrator
- Provide a graceful fallback when agents ignore the file instruction
- Maintain byte-compatible state file format for cross-tool resume (shell ↔ Python)
- Preserve identical orchestration flow, env var interface, and exit codes
- Cover all pure functions with unit tests

**Non-Goals:**
- Modifying agent profile `.md` files or their output contract
- Adding `httpx` as a main package dependency (it's used only by the example script)
- Supporting async/parallel agent execution (agents run sequentially as in the shell version)
- Replacing the shell script (both coexist; user chooses which to run)

## Decisions

**1. File-based handoff over terminal output parsing**

Each agent prompt gets a `RESPONSE FILE INSTRUCTION` block appended, telling it to write its full response to `.tmp/agent-responses/<role>.md` via a heredoc shell command. The orchestrator polls for file existence AND terminal idle/completed status before reading.

*Alternative considered*: Parsing `get_last_output()` with Python regex instead of shell regex. Rejected because it still depends on the provider's output extraction quality and ANSI artifacts.

*Alternative considered*: Using the inbox/message API for inter-agent communication. Rejected because agents don't have inbox awareness in their profiles, and this would require changing the agent contract.

**2. `httpx` sync client over `requests` or `aiohttp`**

`httpx` provides a clean sync API with connection pooling. `requests` would also work but `httpx` is more modern and has a consistent interface for both sync/async if we ever need it.

*Alternative considered*: `requests` — viable but no advantages over `httpx`.
*Alternative considered*: `aiohttp` — overkill since the orchestrator is sequential.

**3. Module-level mutable globals for state**

State variables (`session_name`, `terminal_ids`, `outputs`, etc.) are module-level globals mutated by `save_state()`/`load_state()` and the main loop. This mirrors the shell script's global variables and keeps the single-file script simple.

*Alternative considered*: Encapsulating state in a dataclass or class. Rejected for the same reason the shell script uses globals — it's a single-purpose script, not a library.

**4. Poll loop with file + status check**

`wait_for_response_file()` checks both conditions: (a) response file exists, and (b) terminal status is idle/completed. This avoids reading a partially-written file.

*Alternative considered*: `inotify`/`kqueue` file watching. Rejected because it adds platform-specific complexity for negligible benefit at 2-second poll intervals.

**5. Fallback to `get_last_output()` on timeout**

If the agent finishes (idle/completed) but never wrote the response file, the orchestrator falls back to `api.get_last_output()`. This handles agents that ignore the file instruction without failing the entire run.

## Risks / Trade-offs

- **[Agent ignores file instruction]** → Fallback to `get_last_output()` provides degraded-but-functional behavior. The file instruction is designed to be easy for LLM agents to follow (simple heredoc command).
- **[Partial file write]** → Mitigated by requiring terminal idle/completed status before reading. Agents write via heredoc which is atomic at the shell level.
- **[Stale response file from previous run]** → `clear_stale_response()` deletes the file before each `send_and_wait()` call.
- **[httpx not in project dependencies]** → The script is in `examples/` and has its own `import httpx`. Users must `pip install httpx` separately. This is documented by the import error.
