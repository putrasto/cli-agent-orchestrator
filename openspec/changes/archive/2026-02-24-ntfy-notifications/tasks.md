## 1. Config Key

- [x] 1.1 Add `"notifications"` to `VALID_TOP_LEVEL_KEYS` in `run_orchestrator_loop.py`
- [x] 1.2 Add `("notifications.ntfy_topic", "NTFY_TOPIC", "", str)` to `_CONFIG_KEYS`
- [x] 1.3 Add `global NTFY_TOPIC` and `NTFY_TOPIC = cfg["NTFY_TOPIC"]` in `_apply_config()`

## 2. Notify Helper

- [x] 2.1 Add `import urllib.request` at top of file
- [x] 2.2 Add `notify(title, message, priority=3)` function using `urllib.request` — POST to `https://ntfy.sh/<NTFY_TOPIC>`, 5s timeout, try/except that logs failures, returns immediately when `NTFY_TOPIC` is empty

## 3. Notification Call Sites

- [x] 3.1 PASS: call `notify("Pipeline PASS", ...)` at the `log("FINAL: PASS")` site
- [x] 3.2 FAIL (max rounds): call `notify("Pipeline FAIL", ..., priority=4)` at the max-rounds-exhausted site
- [x] 3.3 Error/timeout: in the main loop, catch `RuntimeError` (with "entered ERROR state" in message) and `TimeoutError` from `send_and_wait()`, call `notify("Pipeline error", ..., priority=4)`, then re-raise
- [x] 3.4 Stuck agent: call `notify("Agent needs attention", ..., priority=5)` in the `waiting_user_answer` handler when `AUTO_ACCEPT_PERMISSIONS` is off — add `_stuck_notified: set[str]` tracker, send at most once per role per turn, reset in `send_and_wait()`

## 4. Tests

- [x] 4.1 Test `notify()` sends POST with correct URL, headers (`Title`, `Priority`), and body when topic is set (mock `urllib.request.urlopen`)
- [x] 4.2 Test `notify()` is a no-op when topic is empty
- [x] 4.3 Test `notify()` catches exceptions and logs without raising
- [x] 4.4 Test `NTFY_TOPIC` config key parsing from env var
- [x] 4.5 Test JSON config with `{"notifications": {"ntfy_topic": "..."}}` passes validation (not rejected as unknown key)

## 5. Verification

- [x] 5.1 Run orchestrator tests: `.venv/bin/pytest test/examples/test_orchestrator_loop_unit.py -v`
- [x] 5.2 Syntax check `run_orchestrator_loop.py`
