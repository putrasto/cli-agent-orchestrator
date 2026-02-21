## 1. Core Implementation

- [x] 1.1 Add `agent_started` flag and startup guard logic to `wait_for_response_file()` in `run_orchestrator_loop.py`: initialize `agent_started = False`, set True when `status not in ("idle", "completed")`, skip grace timer when not started, add startup timeout fallback using `IDLE_GRACE_SECONDS`

## 2. Update Existing Tests

- [x] 2.1 Update `test_fallback_on_idle_grace_expired` (line 832): change `get_status` mock from constant `"completed"` to a sequence that includes `"processing"` before `"completed"`, and update `time.monotonic` side_effect to account for the startup guard phase
- [x] 2.2 Update `test_strict_mode_raises_on_idle_grace_expired` (line 847): same change — include `"processing"` in status mock sequence before `"completed"`, update time mock accordingly

## 3. New Tests — Startup Guard

- [x] 3.1 Add `test_startup_guard_blocks_premature_grace`: mock get_status to return "completed" 5 times (stale), then "processing", then "idle" + file exists → verify returns file content without RuntimeError
- [x] 3.2 Add `test_startup_guard_timeout_fallback`: mock get_status to always return "completed", mock time.monotonic to exceed IDLE_GRACE_SECONDS for startup then again for grace → verify warning logged, then RuntimeError after total 2 × IDLE_GRACE_SECONDS (strict mode)
- [x] 3.3 Add `test_startup_guard_waiting_user_answer_counts_as_started`: mock get_status to return "waiting_user_answer" then "idle" + file exists → verify agent_started triggers and returns file content
- [x] 3.4 Add `test_startup_guard_fast_agent_with_file`: mock get_status to return "processing" once then "idle" + file exists → verify immediate return
- [x] 3.5 Add `test_startup_guard_response_file_during_startup`: mock get_status to return "completed" (stale) + file exists → verify returns file content immediately (file check precedes startup guard)
- [x] 3.6 Add `test_startup_guard_flicker_sequence`: mock get_status to return "completed"(stale) → "processing"(1 poll) → "completed"(repeated, no file) → "processing" → "idle" + file → verify idle_since resets on each processing observation and returns file content

## 4. Spec and Documentation

- [x] 4.1 Sync delta spec to main spec: update `openspec/specs/file-based-handoff/spec.md` with the MODIFIED requirement from the delta spec
- [x] 4.2 Update `examples/agnostic-3agents/README.md`: update `IDLE_GRACE_SECONDS` description to note dual role (startup timeout guard + idle grace window)
