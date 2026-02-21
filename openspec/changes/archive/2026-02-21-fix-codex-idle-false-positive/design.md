## Context

The Codex provider (`src/cli_agent_orchestrator/providers/codex.py`) detects terminal status by analyzing the last 25 lines of tmux output. It uses regex patterns to identify idle prompts, processing signals, user/assistant markers, and errors. The orchestrator's `wait_for_response_file()` depends on terminal status transitioning to `idle`/`completed` before accepting the response file.

Two bugs exist in the detection logic:

1. `PROCESSING_PATTERN` matches generic English words ("running", "working") in agent narrative text, causing false-processing that blocks idle detection even when clear idle signals are present.
2. `USER_PREFIX_PATTERN` uses `\s+` which matches `\n`, causing a standalone `›` prompt line to consume the following line (e.g., `100% context left`) as part of the match, falsely treating the idle prompt as a user input line.

## Goals / Non-Goals

**Goals:**
- Fix false-processing: narrative keywords no longer block idle detection
- Fix false-idle: standalone `›` prompt no longer misdetected as user input
- Existing 2 failing tests pass after the fix
- No regressions in other status detection tests

**Non-Goals:**
- Refactoring the overall detection architecture
- Changing how other providers (Q CLI, Kiro CLI, Claude Code) detect status
- Adding new status detection capabilities beyond fixing these two bugs

## Decisions

### D1: Only `has_active_work_ui` blocks idle detection, not `has_processing_keyword`

**Choice:** Replace `has_processing_signal` with `has_active_work_ui` in the two places that gate idle detection (line 134 in `has_v104_idle_prompt` and line 172 in the status decision branch).

**Rationale:** `ACTIVE_WORK_UI_PATTERN` (`esc to interrupt`, `• Exploring`) matches Codex-specific UI indicators that only appear during genuine processing. `PROCESSING_PATTERN` matches generic English words that routinely appear in agent conversation. Other providers (Q CLI, Kiro CLI) don't use keyword-based processing detection at all — they rely on prompt presence/absence. The default status is already PROCESSING when no idle signals are detected, so the keyword check adds no value when idle signals are absent.

Additionally, tighten `\bExploring\b` to `•\s+Exploring\b` in `ACTIVE_WORK_UI_PATTERN` to anchor it to the Codex bullet prefix. This prevents narrative text like "I was exploring the codebase" from causing false positives — the same class of bug we're fixing for `PROCESSING_PATTERN`.

**Alternative considered:** Narrowing the tail window from 25 to 5 lines for processing keywords. Rejected because even 5 lines can contain narrative text.

### D2: Fix `USER_PREFIX_PATTERN` with horizontal-only whitespace

**Choice:** Change `›\s+\S` to `›[ \t]+\S` in `USER_PREFIX_PATTERN` so `\s+` doesn't match newlines.

**Rationale:** The `›` prompt followed by user text is always on a single line. Cross-line matching is never correct — it only creates false matches where `›\n100%...` looks like `› 1` (user input). Using `[ \t]+` restricts to horizontal whitespace, matching the visual intent.

**Alternative considered:** Adding `$` anchor after `\S`. Rejected because the pattern uses `re.finditer` over the full output to find all user markers, not just end-of-line matches.

## Risks / Trade-offs

- **[Risk] Agent genuinely processing but `ACTIVE_WORK_UI_PATTERN` not visible yet** → The default status without any idle signal is PROCESSING (line 163-164). If no idle prompt is detected, status is PROCESSING regardless. The keyword check only matters when both idle signals AND keywords are present — which is the false positive scenario.
- **[Risk] New Codex version changes UI patterns** → `ACTIVE_WORK_UI_PATTERN` already handles multiple UI variants. If a new version changes these, the pattern needs updating — same as today, no new risk introduced.
