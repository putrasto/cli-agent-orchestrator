## Context

The orchestrator loop (`run_orchestrator_loop.py`) manages a 3-phase cycle: analyst → programmer → tester. On tester FAIL, the loop increments the round and restarts at the analyst phase. Currently, the FAIL branch (lines 1294-1304) extracts condensed test evidence into the `feedback` global, then wipes all `outputs` — including the programmer's summary. The analyst receives only the tester's condensed failure evidence and must re-explore the codebase blindly.

Two globals carry inter-round feedback: `feedback` (tester → analyst) and `analyst_feedback`/`programmer_feedback` (peer reviews, reset on new round). The state persistence (`save_state`/`load_state`) serializes these plus `outputs` to JSON. The condensation system uses `MAX_FEEDBACK_LINES=30` for both peer review notes and tester evidence.

## Goals / Non-Goals

**Goals:**
- Give the analyst visibility into what the programmer changed when retrying after FAIL
- Ensure this context survives process resume via state persistence
- Give tester evidence enough room (120 lines) without inflating peer review feedback
- Keep token cost minimal: only analyst sees the extra context, only on retry rounds

**Non-Goals:**
- Changing the analyst profile or prompt structure beyond adding one context block
- Providing programmer context to any agent other than the analyst
- Changing peer review condensation behavior (stays at 30 lines)
- Adding new condensation strategies or cross-phase logic

## Decisions

### 1. New global `programmer_context_for_retry` with state persistence

Add a module-level global `programmer_context_for_retry: str = ""`. In the FAIL branch of the main loop, before wiping `outputs`, set it from `condense_programmer_for_tester(outputs["programmer"])` — reusing the existing condensation function that extracts "Files changed" + "Behavior implemented" sections, capped at `MAX_CROSS_PHASE_LINES` (40 lines).

Persist this field in `save_state()` under key `"programmer_context_for_retry"` and restore it in `load_state()`. This ensures resume after a FAIL round preserves the context.

**Why reuse `condense_programmer_for_tester`**: It already extracts exactly the sections the analyst needs (what changed, what behavior was implemented). No new condensation logic needed.

**Alternative considered**: Storing raw `outputs["programmer"]` — rejected because it would add unbounded content to state and analyst prompt, directly contradicting the token-conservation goal.

### 2. Inject context in `build_analyst_prompt()` only for round > 1

Add a block after "Latest tester feedback:" that shows the condensed programmer summary. Only include when `round_num > 1` and `programmer_context_for_retry` is non-empty. Label it clearly as context-only:

```
Previous round programmer changes (context only):
<condensed summary>
```

This appears only in the analyst prompt. The `build_programmer_prompt()`, `build_tester_prompt()`, and peer review prompts are unchanged.

**Why not a separate condensation function**: The analyst needs the same info the tester gets — what files changed, what behavior was implemented. The existing condensation is sufficient.

### 3. Split line limits: `MAX_TEST_EVIDENCE_LINES` separate from `MAX_FEEDBACK_LINES`

Add `MAX_TEST_EVIDENCE_LINES` (default 120) as a new config key. `extract_test_evidence()` uses this instead of `MAX_FEEDBACK_LINES`. `extract_review_notes()` continues using `MAX_FEEDBACK_LINES` (default 30).

Config pipeline additions:
- `_CONFIG_KEYS` entry: `("condensation.max_test_evidence_lines", "MAX_TEST_EVIDENCE_LINES", 120, int)`
- `_apply_config()`: assign to global `MAX_TEST_EVIDENCE_LINES`
- JSON mapping in spec: `condensation.max_test_evidence_lines` → `MAX_TEST_EVIDENCE_LINES`
- Sample configs: add to condensation section in `config-fresh.json` and `config-incremental.json`

**Why 120**: Complex test failures (multi-file integration tests) need room for command output, stack traces, and the "Recommended next fix" section. 120 lines is ~4x the current limit but still bounded. The cost is paid only on FAIL retries going to the analyst — not on every round.

**Alternative considered**: Bumping `MAX_FEEDBACK_LINES` to 120 globally — rejected because peer review feedback is sent on every review cycle (potentially 3x per phase), making the token cost multiplicative.

## Risks / Trade-offs

- **[State format change]** → Adding `programmer_context_for_retry` to state JSON. Backward compatible: `load_state()` uses `.get()` with default `""`, so old state files without this field load fine.
- **[120-line evidence in analyst prompt]** → Increases analyst prompt size on retry rounds. Mitigated by: only on FAIL retries (not normal flow), only for analyst (not other 4 agents), and bounded at 120 lines.
- **[Reusing `condense_programmer_for_tester` for analyst context]** → If the tester condensation logic changes in future, analyst context changes too. Acceptable: both need the same information (files changed, behavior implemented).
