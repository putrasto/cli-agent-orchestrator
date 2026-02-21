## Why

The Codex provider's status detection has two bugs that cause incorrect status reporting:

1. **False-processing (orchestrator hangs):** When the Codex agent finishes work and returns to its idle prompt, words like "running" or "working" in the agent's narrative text within the last 25 lines match `PROCESSING_PATTERN`, overriding valid idle signals. The orchestrator's `wait_for_response_file()` requires both the response file AND terminal idle status, so it polls forever.

2. **False-idle (COMPLETED reported as IDLE):** `USER_PREFIX_PATTERN` uses `\s+` which matches newlines, so a standalone `›` prompt line followed by `100% context left` is falsely treated as a user prompt (`›\n1` matches `›\s+\S`). This makes `last_user` point to the idle prompt itself, `assistant_after_last_user` becomes False, and status falls to IDLE instead of COMPLETED. Two existing tests already fail because of this.

## What Changes

- **Fix 1 — Processing keyword override:** Stop letting generic English keyword matches (`PROCESSING_PATTERN`) override idle detection. Only let Codex-specific UI patterns (`ACTIVE_WORK_UI_PATTERN`: "esc to interrupt", "• Exploring") block idle detection. Tighten `\bExploring\b` to `•\s+Exploring\b` to prevent narrative false positives (e.g., "I was exploring the codebase").
- **Fix 2 — USER_PREFIX_PATTERN newline overmatch:** Change `\s+` to `[ \t]+` in the `›` branch of `USER_PREFIX_PATTERN` so it only matches horizontal whitespace, preventing cross-line false matches.
- Add tests covering the false-processing scenario and verifying `has_active_work_ui` still correctly blocks idle detection. Fix the 2 existing failing tests.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `file-based-handoff`: The Codex provider's status detection is part of the terminal status pipeline that `wait_for_response_file()` depends on. Two behavioral changes: (1) idle detection no longer blocked by narrative keyword matches, only by Codex-specific UI indicators; (2) standalone `›` prompt lines no longer falsely detected as user input.

## Impact

- `src/cli_agent_orchestrator/providers/codex.py` — `USER_PREFIX_PATTERN` regex fix, and two lines in `_analyze_clean_output()`: `has_v104_idle_prompt` computation and the status decision branch.
- `test/providers/test_codex_provider_unit.py` — 2 existing tests now pass, plus new tests for false-processing scenario and active work UI blocking.
- No API changes, no config changes, no breaking changes.
