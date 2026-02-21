## 1. JSON config loading

- [x] 1.1 Add `load_config()` function that reads `sys.argv[1]` as JSON, maps nested keys (`limits.*`, `condensation.*`, `handoff.*`) plus `start_agent` to flat config keys, applies env var overrides (non-empty only), and falls through to hardcoded defaults
- [x] 1.2 Add config validation: unknown top-level JSON keys cause fatal error, unknown agent role names cause fatal error, invalid provider values cause fatal error, invalid `START_AGENT`/`start_agent` value causes fatal error
- [x] 1.3 Replace all 25 module-level `os.getenv()` globals with values from `load_config()` result (includes new `START_AGENT`, default `analyst`)
- [x] 1.4 Add tests: JSON overrides default, env var overrides JSON, `START_AGENT` env var overrides JSON `start_agent`, empty env var treated as unset, missing file exits with error, invalid JSON exits with error, unknown top-level key fatal, unknown agent role fatal, invalid provider fatal, invalid start agent fatal, no config file uses env-only (backward compat)

## 2. Per-agent provider

- [x] 2.1 Add `AGENT_CONFIG` dict built by `load_config()` — maps each role to `{"provider": ..., "profile": ...}` with inheritance from top-level `provider` and default profiles
- [x] 2.2 Change `ApiClient.create_session()` and `ApiClient.create_terminal()` to accept a `provider` parameter instead of using global `PROVIDER`
- [x] 2.3 Update `init_new_run()` to read provider/profile from `AGENT_CONFIG[role]` for each terminal creation call
- [x] 2.4 Add tests: mixed providers create terminals with correct provider params, missing agent provider inherits top-level, missing profile uses role default, agents section omitted uses all defaults

## 3. Terminal rename

- [x] 3.1 After each terminal creation in `init_new_run()`, send `/rename {role}-{terminal_id}` via `api.send_input()`, then poll `api.get_status()` for up to 5 seconds waiting for idle
- [x] 3.2 Wrap rename in try/except — log warning and proceed on any failure (send error, timeout, non-idle)
- [x] 3.3 Add tests: rename sent with correct format (`analyst-da33cf00`, `peer_analyst-fae0481d`), rename failure is non-fatal (logged, continues)

## 4. Partial creation cleanup

- [x] 4.1 Wrap terminal creation loop in `init_new_run()` with try/except — on failure, call `api.exit_terminal()` for all already-created terminal IDs, then exit with code 1
- [x] 4.2 Add test: creation fails on 3rd terminal, verify `exit_terminal` called for first 2, then SystemExit with code 1

## 5. Explore-before-ff on retry

- [x] 5.1 In `build_analyst_prompt()`, when `round_num > 1`, change task instructions to: (1) use OpenSpec explore skill to investigate the test failure, (2) then use OpenSpec fast-forward skill to update artifacts
- [x] 5.2 Add tests: round 1 prompt contains "Explore the codebase" + "fast-forward skill", round 2 prompt contains "explore skill to investigate the test failure" + "fast-forward skill to update"

## 6. State file per-agent provider

- [x] 6.1 Update `save_state()` to write `terminals` as `{role: {"id": tid, "provider": provider}}` instead of `{role: tid}`
- [x] 6.2 Update `load_state()` to accept both new format (dict) and old format (plain string, treated as `{"id": value, "provider": top_level_provider}`)
- [x] 6.3 Update `verify_resume_terminals()` to check that each terminal's stored provider matches the current `AGENT_CONFIG` — mismatch logs a warning but proceeds (provider may have been intentionally changed)
- [x] 6.4 Add tests: state roundtrip with mixed providers preserves all values, old-format state file loads correctly with provider fallback, unreachable terminal on resume exits with error, provider mismatch on resume logs warning

## 7. Start agent selection

- [x] 7.1 Add `START_AGENT` setting (JSON `start_agent` + env `START_AGENT`) with allowed values: `analyst`, `peer_analyst`, `programmer`, `peer_programmer`, `tester`; default `analyst`
- [x] 7.2 For fresh runs, dispatch selected `START_AGENT` role first exactly (including peer roles)
- [x] 7.3 On first dispatch only, bypass missing-upstream fallback guards; if upstream output is missing, include explicit placeholder text in the prompt
- [x] 7.4 For resume runs, ignore `START_AGENT` and use `current_phase` from state file
- [x] 7.5 Add tests: default starts at analyst, start at peer_analyst, start at programmer, start at peer_programmer, start at tester, peer_analyst first-dispatch placeholder behavior, peer_programmer first-dispatch placeholder behavior, resume ignores `START_AGENT`

## 8. Sample config files and shell script removal

- [x] 8.1 Create `examples/agnostic-3agents/config-fresh.json` with all sections populated including mixed-provider agents and explicit `start_agent` example
- [x] 8.2 Create `examples/agnostic-3agents/config-incremental.json` with note that incremental behavior is driven by prompt file content
- [x] 8.3 Create `examples/agnostic-3agents/config-resume.json` with `resume: true` and minimal settings
- [x] 8.4 Delete `examples/agnostic-3agents/run_orchestrator_loop.sh` (replaced by Python orchestrator)
- [x] 8.5 Update `examples/agnostic-3agents/README.md` with JSON config invocation examples and remove shell script references
