## Why

When the tester reports FAIL, the current orchestrator restarts the full pipeline (analyst → peer_analyst → programmer → peer_programmer → tester), wasting tokens on re-analysis when the problem is almost always an implementation bug. The analyst already created correct OpenSpec artifacts in round 1 — re-running analyst and peer_analyst on retry rounds adds cost and latency without proportional value.

## What Changes

- **On tester FAIL, skip analyst and peer_analyst phases**: retry rounds go directly to programmer → peer_programmer → tester instead of the full 5-agent pipeline.
- **Modified programmer prompt on retry**: includes condensed test failure evidence and instructs the programmer to read OpenSpec artifacts directly from disk (the source of truth) rather than relying on a cached analyst summary. The programmer prompt on retry does NOT include `outputs["analyst"]` — artifacts on disk may have been updated by the programmer in prior retries, making cached analyst output stale.
- **Programmer allowed to update OpenSpec artifacts on retry**: when the failure indicates a spec/design issue rather than a pure implementation bug, the programmer can use `/opsx:explore` and `/opsx:ff` to update artifacts before fixing the code.
- **Selective output clearing on FAIL**: only `outputs["programmer"]`, `outputs["programmer_review"]`, and `outputs["tester"]` are cleared. `outputs["analyst"]` and `outputs["analyst_review"]` are preserved for state consistency, but are NOT used in retry prompts (artifacts on disk are the source of truth).
- **Always-on behavior, no escalation**: this is not configurable — retry rounds always use the shortened pipeline. There is no automatic escalation back to the analyst after N failures. The programmer's ability to update OpenSpec artifacts covers the case where the root cause is a spec/design issue.
- **No special case for missing analyst output on retry**: if the run started at `START_AGENT=programmer` or later and no real analyst pass exists, `outputs["analyst"]` contains the `_UPSTREAM_PLACEHOLDER`. The shortened retry still applies — the programmer works from artifacts on disk and test failure feedback, not from analyst output.

## Capabilities

### New Capabilities
- `shortcut-retry-pipeline`: Defines the shortened retry flow (programmer → peer_programmer → tester) triggered on tester FAIL, including modified prompt construction, output preservation, and phase transition logic.

### Modified Capabilities
- `python-orchestrator`: The main loop FAIL handler changes phase transition from `PHASE_ANALYST` to `PHASE_PROGRAMMER`, and `build_programmer_prompt()` gains a test-failure context parameter for retry rounds.
- `fail-retry-context`: The `programmer_context_for_retry` variable is still populated on FAIL, but now feeds the programmer prompt directly (instead of only the analyst prompt). The analyst prompt inclusion on retry rounds is removed since the analyst is no longer invoked on retries.

## Impact

- **Code**: `examples/agnostic-3agents/run_orchestrator_loop.py` — FAIL handler (lines 1520-1531), `build_programmer_prompt()`, main loop phase logic.
- **Tests**: `test/examples/test_orchestrator_loop_unit.py` — existing FAIL-retry tests need updating; new tests for: shortened pipeline path, resume-in-retry state (phase=programmer on round>1), missing analyst output on retry (`START_AGENT!=analyst`), selective output clearing (analyst preserved, programmer/tester cleared).
- **Specs**: `fail-retry-context` spec needs updating (analyst prompt retry context requirement becomes obsolete; programmer prompt gains test failure context). `python-orchestrator` spec needs updating (prompt builder and FAIL handler requirements).
- **Token usage**: Significant reduction on retry rounds — eliminates 2 agent invocations (analyst + peer_analyst review cycles) per retry.
