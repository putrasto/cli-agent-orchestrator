## Context

The orchestrator loop in `run_orchestrator_loop.py` runs a 5-agent pipeline: analyst → peer_analyst → programmer → peer_programmer → tester. When the tester reports FAIL, the current code sets `current_phase = PHASE_ANALYST` and increments `current_round`, restarting the full pipeline. Each analyst + peer_analyst cycle costs 2+ agent invocations with review loops, consuming significant tokens for re-analysis that rarely changes the OpenSpec artifacts.

The FAIL handler currently (lines 1520-1531):
1. Extracts test evidence into `feedback`
2. Saves condensed programmer output to `programmer_context_for_retry`
3. Clears ALL `outputs`
4. Resets `analyst_feedback` and `programmer_feedback`
5. Sets `current_phase = PHASE_ANALYST`

The `build_programmer_prompt()` function currently takes `analyst_out` as a required parameter and includes it as "System analyst handoff" in the prompt.

## Goals / Non-Goals

**Goals:**
- Reduce token waste on retry rounds by skipping analyst and peer_analyst phases
- Give the programmer test failure context directly so it can diagnose and fix
- Allow the programmer to update OpenSpec artifacts when the failure is a spec/design issue
- Maintain correct state management for resume and START_AGENT edge cases

**Non-Goals:**
- Adding a configurable escalation mechanism back to analyst after N failures
- Changing the round-1 (normal) pipeline flow
- Modifying the peer_programmer review prompt or tester prompt
- Changing the condensation or review approval logic

## Decisions

### 1. FAIL handler sets `current_phase = PHASE_PROGRAMMER` instead of `PHASE_ANALYST`

**Rationale**: The main loop uses `if current_phase == PHASE_ANALYST` / `if current_phase == PHASE_PROGRAMMER` guards. Setting phase to PROGRAMMER on FAIL causes the loop to skip the analyst block entirely on the next iteration. No structural change to the loop needed — the existing phase guards handle it.

**Alternative considered**: Adding a `skip_analyst` boolean flag. Rejected — phase-based control is simpler and consistent with existing START_AGENT skip logic.

### 2. Selective output clearing on FAIL (preserve analyst outputs)

On FAIL, clear only:
- `outputs["programmer"]`
- `outputs["programmer_review"]`
- `outputs["tester"]`

Preserve:
- `outputs["analyst"]` — needed for state file consistency and potential debugging
- `outputs["analyst_review"]` — same

**Rationale**: The programmer phase has a guard (line 1436) that falls back to `PHASE_ANALYST` if `outputs["analyst"]` is empty. Preserving it prevents this fallback from triggering on retry rounds. Even though the retry programmer prompt won't include analyst output (it uses artifacts on disk), the value must be non-empty to pass the guard.

### 3. Programmer retry prompt uses test failure + artifact-from-disk approach

On retry rounds (`round_num > 1`), `build_programmer_prompt()` changes:
- **Replaces** "System analyst handoff" block with "Test failure feedback" block containing condensed test evidence
- **Adds** instruction to read OpenSpec artifacts from disk via `/opsx:explore` and `/opsx:ff`
- **Adds** instruction that programmer may update artifacts if the failure indicates a spec/design issue
- **Does NOT** include `outputs["analyst"]` — artifacts on disk are the source of truth

On round 1, prompt is unchanged (still receives analyst handoff as today).

**Rationale**: After round 1, the programmer may have modified artifacts. Using `outputs["analyst"]` would present stale context. Artifacts on disk are always current.

### 4. `programmer_context_for_retry` feeds programmer prompt (not analyst)

Currently `programmer_context_for_retry` is only used in `build_analyst_prompt()`. Since the analyst is no longer invoked on retries:
- Remove it from `build_analyst_prompt()` (dead code on retry path)
- Add it to `build_programmer_prompt()` on retry rounds as "Your previous changes" context

**Rationale**: The programmer benefits from seeing what it changed last round, especially if its context was condensed.

### 5. No changes to `analyst_feedback` / `programmer_feedback` reset

On FAIL, the current code resets both to `"None yet."`. This remains unchanged — on retry, `programmer_feedback` starts fresh (peer_programmer hasn't reviewed yet), and `analyst_feedback` is irrelevant (analyst isn't invoked).

## Risks / Trade-offs

- **[Risk] Programmer may lack domain context that analyst would provide on complex failures** → Mitigated by: programmer can read OpenSpec artifacts on disk; programmer can use `/opsx:explore` to investigate; programmer has its own conversation history from round 1.
- **[Risk] Programmer's OpenSpec artifact edits may diverge from original analyst intent** → Accepted trade-off: this is preferable to spending tokens re-running analyst. The tester validates the end result regardless.
- **[Risk] `outputs["analyst"]` guard at line 1436 could become stale assumption** → Mitigated by: preserving analyst output on FAIL so the guard always passes on retry rounds. Guard behavior is unchanged.
