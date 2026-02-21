## Context

The orchestrator (`examples/agnostic-3agents/run_orchestrator_loop.py`) currently uses 24 module-level globals initialized from `os.getenv()`. Configuration is flat — one `PROVIDER` for all agents, no structured grouping. The orchestrator works but is hard to invoke correctly (long shell one-liners) and lacks production features: mixed providers, intelligent retry prompts, debuggable terminal names, and a configurable start stage.

The CAO server already supports per-terminal provider selection and terminal input for rename commands. All changes are in the orchestrator script; no server changes needed.

## Goals / Non-Goals

**Goals:**
- JSON config file as primary configuration with env var override
- Per-agent provider/profile selection
- Start-agent selection for fresh runs
- Two-phase analyst prompt on retry rounds (explore then fast-forward)
- Human-readable terminal names in tmux
- Backward compatibility: env-only invocation still works

**Non-Goals:**
- YAML/TOML config formats (JSON only)
- GUI or interactive config builder
- Dynamic provider switching mid-run
- Changes to the CAO server API
- Config file schema validation library (use simple dict checks)

## Decisions

### D1: Config loading — single `load_config()` function at startup

Load order: `sys.argv[1]` (JSON path) → env vars → hardcoded defaults. A single `load_config()` function returns a flat `Config` dict. Module-level globals are replaced by reading from this dict.

**Alternative considered**: dataclass/pydantic model. Rejected — adds a dependency or boilerplate for a single-file script. A typed dict with helper functions is sufficient.

Implementation:
1. If `sys.argv[1]` exists, parse it as JSON (no extension check — any valid JSON file works)
2. Map JSON nested keys to flat config keys (e.g., `limits.max_rounds` → `MAX_ROUNDS`, `start_agent` → `START_AGENT`)
3. For each flat key, check if an env var with the same name is set; if so, it overrides the JSON value
4. Apply hardcoded defaults for any key still unset
5. The `agents` section is JSON-only — no env var mapping
6. `START_AGENT` defaults to `analyst` when unset

### D2: Agent config — `agents` dict with role → {provider, profile}

A module-level `AGENT_CONFIG` dict maps each role to its provider and profile. Built during `load_config()` by merging the `agents` JSON section with defaults.

Example result when JSON specifies mixed providers:
```
# After load_config() with {"agents": {"analyst": {"provider": "claude_code"}, "peer_analyst": {"provider": "codex"}, ...}}
AGENT_CONFIG = {
    "analyst":        {"provider": "claude_code", "profile": "system_analyst"},
    "peer_analyst":   {"provider": "codex",       "profile": "peer_system_analyst"},
    "programmer":     {"provider": "claude_code", "profile": "programmer"},
    "peer_programmer":{"provider": "codex",       "profile": "peer_programmer"},
    "tester":         {"provider": "codex",       "profile": "tester"},
}
```

If `agents` is absent from JSON, all roles inherit the top-level `PROVIDER` default and their default profile. If a role entry has no `provider`, it inherits the top-level default. If no `profile`, it uses the default for that role.

Validation at startup: (a) every key in `agents` must be one of the 5 recognized roles — unknown keys are fatal, (b) every provider value must be one of `codex`, `claude_code`, `q_cli`, `kiro_cli`.

### D3: ApiClient — provider passed per-call

`create_session()` and `create_terminal()` currently use the global `PROVIDER`. Change their signatures to accept a `provider` parameter:

```python
def create_session(self, profile: str, provider: str) -> dict:
def create_terminal(self, session_name: str, profile: str, provider: str) -> dict:
```

`init_new_run()` reads from `AGENT_CONFIG[role]` to get the provider for each terminal creation call.

### D4: Terminal rename — best-effort after creation

After each terminal is created in `init_new_run()`, send a rename command via `api.send_input()`:

```python
rename_label = f"{role_short}-{terminal_id}"
api.send_input(terminal_id, f"/rename {rename_label}")
```

Role labels use underscores matching the config keys: `analyst`, `peer_analyst`, `programmer`, `peer_programmer`, `tester`.

Then poll `api.get_status()` for up to 5 seconds waiting for idle. If it doesn't reach idle, log a warning and proceed. If `send_input` raises an exception, catch it, log warning, proceed.

The rename is purely cosmetic — it only affects what appears in the tmux window title for providers that support it. No state or API behavior depends on it.

### D5: Explore-before-ff analyst prompt on retry

In `build_analyst_prompt()`, when `round_num > 1`, the task instructions change:

Round 1:
```
"1) Explore the codebase."
"2) Create/update all OpenSpec artifacts using the OpenSpec fast-forward skill."
```

Round 2+:
```
"1) Use the OpenSpec explore skill to investigate the test failure described in the tester feedback above."
"2) Based on your findings, use the OpenSpec fast-forward skill to update the artifacts."
```

This is a prompt-only change. The agent executes both skills within a single turn. No orchestrator flow change — still one `send_and_wait()` call to the analyst.

### D6: Partial creation cleanup on failure

If terminal creation fails partway through `init_new_run()` (e.g., agent 3/5 fails), the orchestrator calls `api.exit_terminal()` for every terminal ID collected so far, then exits with code 1.

Wrap the creation loop in try/except. On failure, iterate `terminal_ids` values that are non-empty and call `exit_terminal()` for each (ignoring errors during cleanup).

### D7: State file — add per-agent provider info

The state file's `terminals` section currently stores `{role: terminal_id}`. Extend to also record each terminal's provider so resume can verify provider consistency:

```json
"terminals": {
    "analyst": {"id": "da33cf00", "provider": "claude_code"},
    "peer_analyst": {"id": "fae0481d", "provider": "codex"},
    ...
}
```

For backward read-compatibility (Python only): if `terminals.analyst` is a string (old format), treat it as `{"id": value, "provider": PROVIDER}`. The shell script orchestrator is not guaranteed to read the new format — this is a one-way upgrade.

### D8: Sample config files

Create 3 sample JSON files in `examples/agnostic-3agents/`:

- `config-fresh.json` — full config for a fresh run with mixed providers
- `config-incremental.json` — same structure, notes that incremental behavior comes from the prompt file content
- `config-resume.json` — minimal config with `resume: true`

These serve as documentation and copy-paste templates.

### D9: Start-agent selection controls first dispatched role

Add `START_AGENT` as a validated setting with allowed values:
`analyst`, `peer_analyst`, `programmer`, `peer_programmer`, `tester`.

Default: `analyst`.

For fresh runs (`RESUME=0`), dispatch the selected role first:

- `analyst` → analyst dispatch first
- `peer_analyst` → peer analyst dispatch first
- `programmer` → programmer dispatch first
- `peer_programmer` → peer programmer dispatch first
- `tester` → tester dispatch first

Implementation detail:
- On first dispatch only, missing-upstream fallback guards are bypassed so the selected role is actually invoked first.
- If upstream output is unavailable on first dispatch (for example, `peer_analyst` without analyst output), prompt builders receive explicit placeholder text indicating the run started from that role.
- After first dispatch, existing phase/fallback behavior is restored unchanged.

Validation:
- Unknown `START_AGENT` value is fatal at startup with exit code 1.

Resume behavior:
- When resuming from state (`RESUME=1` or auto-resume), persisted `current_phase` remains authoritative and `START_AGENT` is ignored.

## Risks / Trade-offs

| Risk | Severity | Mitigation |
|------|----------|------------|
| JSON config adds a new "thing to get right" alongside env vars | Low | Env-only invocation still works unchanged. JSON is optional. |
| Per-agent provider means mixed tmux sessions (e.g., Claude Code + Codex windows) | Low | CAO server already supports this. Each terminal is independent. |
| Explore-before-ff adds latency and tokens on retry | Low | The explore step produces better root cause analysis, reducing total rounds needed. Agent context window is the natural token limit. |
| Terminal rename may confuse providers that don't support `/rename` | Low | Best-effort with 5s timeout. Provider will either ignore the unknown command or show a harmless error. |
| State file format change (terminals dict-of-dicts vs dict-of-strings) | Medium | Backward-compatible reader: detect old format and convert. Old orchestrator versions cannot read new format — acceptable since this is a one-way upgrade. |
| Start-agent set to peer/programmer/tester without upstream outputs may produce low-signal first pass | Low | First-dispatch placeholders make context explicit; normal fallback logic resumes immediately after first dispatch. |
