# CLAUDE.md

## Project overview

CLI Agent Orchestrator (CAO) — a Python server that manages multiple AI CLI agent terminals via tmux, enabling multi-agent workflows. Supports providers: Codex, Amazon Q CLI, Kiro CLI, Claude Code.

## Quick reference

- **Language**: Python 3.10+
- **Package manager**: uv
- **Entry points**: `cao` (CLI), `cao-server` (FastAPI on :9889), `cao-mcp-server` (MCP server)
- **Source**: `src/cli_agent_orchestrator/`
- **Tests**: `test/`
- **Examples**: `examples/` (orchestrator loops, agent profiles)

## Build and test commands

```bash
# Install dependencies
uv sync

# Run all unit tests (skip integration tests that need live CLI tools)
.venv/bin/pytest test/ --ignore=test/providers/test_q_cli_integration.py -v

# Run specific test file
.venv/bin/pytest test/examples/test_orchestrator_loop_unit.py -v

# Run single test
.venv/bin/pytest test/path/to/test.py::TestClass::test_name -v

# Syntax check a Python file
python3 -c "import ast; ast.parse(open('path/to/file.py').read())"

# Format and lint
uv run black src/ test/
uv run isort src/ test/
uv run mypy src/
```

## Architecture

```
FastAPI (:9889) → Services (session, terminal, inbox, flow) → Providers (codex, q_cli, kiro_cli, claude_code) → tmux sessions
```

Key layers:
- `api/main.py` — REST endpoints for session/terminal/inbox management
- `services/` — business logic (terminal_service creates tmux panes, manages provider lifecycle)
- `providers/` — each provider wraps a CLI tool, detects status (idle/processing/completed/error), extracts output
- `clients/` — tmux and SQLite clients
- `models/` — Pydantic models (Terminal, Session, TerminalStatus)

## Key file paths

| Area | Path |
|------|------|
| API server | `src/cli_agent_orchestrator/api/main.py` |
| Providers | `src/cli_agent_orchestrator/providers/{codex,q_cli,kiro_cli,claude_code}.py` |
| Terminal service | `src/cli_agent_orchestrator/services/terminal_service.py` |
| Constants | `src/cli_agent_orchestrator/constants.py` |
| 3-agent orchestrator (shell) | `examples/agnostic-3agents/run_orchestrator_loop.sh` |
| 3-agent orchestrator (Python) | `examples/agnostic-3agents/run_orchestrator_loop.py` |
| Agent profiles | `examples/agnostic-3agents/{system_analyst,peer_system_analyst,programmer,peer_programmer,tester}.md` |
| Orchestrator tests | `test/examples/test_orchestrator_loop_unit.py` |

## Coding conventions

- Tests use pytest with `asyncio_mode = "strict"`
- Coverage: `--cov=src --cov-report=term-missing` (configured in pyproject.toml)
- Formatting: black (line-length 100), isort (profile "black")
- Type checking: mypy strict mode
- Test fixtures in `test/providers/fixtures/`
- Provider unit tests mock tmux interactions via `unittest.mock`

## State file format (orchestrator loop)

The orchestrator loop persists state to `.tmp/codex-3agents-loop-state.json` with `version: 1`. The Python and shell orchestrators produce byte-compatible state files for cross-tool resume.

## Important env vars (orchestrator loop)

`API`, `PROVIDER`, `WD`, `PROMPT_FILE`, `MAX_ROUNDS` (8), `MAX_REVIEW_CYCLES` (3), `POLL_SECONDS` (2), `RESUME` (0), `STRICT_FILE_HANDOFF` (0), `CLEANUP_ON_EXIT` (0), `STATE_FILE`.

## OpenSpec workflow

The project uses OpenSpec for structured change management. Changes live in `openspec/changes/<name>/` with artifacts: proposal.md, design.md, specs/, tasks.md. Use `/opsx:ff` to fast-forward artifact creation, `/opsx:apply` to implement.
