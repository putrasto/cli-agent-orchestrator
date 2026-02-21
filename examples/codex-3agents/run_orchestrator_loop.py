#!/usr/bin/env python3
"""
Python orchestrator loop with file-based agent handoff.

Replaces the shell-based run_orchestrator_loop.sh with a cleaner mechanism:
each agent writes its final response to a file, the orchestrator polls for
file existence, reads it, deletes it, and passes the content to the next agent.

Uses zero LLM tokens — pure Python doing HTTP + file I/O.
"""

# ── 1. Imports ──────────────────────────────────────────────────────────────

import json
import os
import re
import shlex
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ── 2. Configuration ────────────────────────────────────────────────────────

API = os.getenv("API", "http://localhost:9889")
PROVIDER = os.getenv("PROVIDER", "codex")
WD = os.getenv("WD", os.getcwd())
PROMPT = os.getenv("PROMPT", "")
PROMPT_FILE = os.getenv("PROMPT_FILE", "")
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "8"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "2"))
MAX_REVIEW_CYCLES = int(os.getenv("MAX_REVIEW_CYCLES", "3"))
PROJECT_TEST_CMD = os.getenv("PROJECT_TEST_CMD", "")
MIN_REVIEW_CYCLES_BEFORE_APPROVAL = int(
    os.getenv("MIN_REVIEW_CYCLES_BEFORE_APPROVAL", "2")
)
REQUIRE_REVIEW_EVIDENCE = os.getenv("REQUIRE_REVIEW_EVIDENCE", "1") == "1"
REVIEW_EVIDENCE_MIN_MATCH = int(os.getenv("REVIEW_EVIDENCE_MIN_MATCH", "3"))
RESUME = os.getenv("RESUME", "0") == "1"
MAX_STRUCTURED_OUTPUT_LINES = int(os.getenv("MAX_STRUCTURED_OUTPUT_LINES", "60"))
CONDENSE_EXPLORE_ON_REPEAT = os.getenv("CONDENSE_EXPLORE_ON_REPEAT", "1") == "1"
CONDENSE_REVIEW_FEEDBACK = os.getenv("CONDENSE_REVIEW_FEEDBACK", "1") == "1"
MAX_FEEDBACK_LINES = int(os.getenv("MAX_FEEDBACK_LINES", "30"))
CONDENSE_UPSTREAM_ON_REPEAT = os.getenv("CONDENSE_UPSTREAM_ON_REPEAT", "1") == "1"
CONDENSE_CROSS_PHASE = os.getenv("CONDENSE_CROSS_PHASE", "1") == "1"
MAX_CROSS_PHASE_LINES = int(os.getenv("MAX_CROSS_PHASE_LINES", "40"))
STATE_FILE = os.getenv("STATE_FILE", str(Path(WD) / ".tmp" / "codex-3agents-loop-state.json"))
CLEANUP_ON_EXIT = os.getenv("CLEANUP_ON_EXIT", "0") == "1"

RESPONSE_DIR = Path(WD) / ".tmp" / "agent-responses"
RESPONSE_TIMEOUT = int(os.getenv("RESPONSE_TIMEOUT", "1800"))
IDLE_GRACE_SECONDS = int(os.getenv("IDLE_GRACE_SECONDS", "30"))
STRICT_FILE_HANDOFF = os.getenv("STRICT_FILE_HANDOFF", "1") == "1"

EXPLORE_HEADER = "*** ORIGINAL EXPLORE SUMMARY ***"
SCENARIO_HEADER = "*** SCENARIO TEST ***"

PHASE_ANALYST = "analyst"
PHASE_PROGRAMMER = "programmer"
PHASE_TESTER = "tester"
PHASE_DONE = "done"

RESPONSE_FILES = {
    "analyst": "analyst_summary.md",
    "analyst_review": "analyst_review.md",
    "programmer": "programmer_summary.md",
    "programmer_review": "programmer_review.md",
    "tester": "test_result.md",
}

APPROVED_REVIEW_RE = re.compile(r"^\s*REVIEW_RESULT:\s*APPROVED\b", re.MULTILINE | re.IGNORECASE)
REVIEW_RESULT_RE = re.compile(r"^\s*REVIEW_RESULT:\s*(APPROVED|REVISE)\b", re.MULTILINE | re.IGNORECASE)
PASS_RESULT_RE = re.compile(r"^\s*RESULT:\s*PASS\b", re.MULTILINE | re.IGNORECASE)
TEST_RESULT_RE = re.compile(r"^\s*RESULT:\s*(PASS|FAIL)\b", re.MULTILINE | re.IGNORECASE)

# ── 3. Logging ──────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── 4. API Client ──────────────────────────────────────────────────────────


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=30.0)

    def create_session(self, profile: str) -> dict:
        r = self._client.post(
            "/sessions",
            params={"provider": PROVIDER, "agent_profile": profile, "working_directory": WD},
        )
        r.raise_for_status()
        return r.json()

    def create_terminal(self, session_name: str, profile: str) -> dict:
        r = self._client.post(
            f"/sessions/{session_name}/terminals",
            params={"provider": PROVIDER, "agent_profile": profile, "working_directory": WD},
        )
        r.raise_for_status()
        return r.json()

    def send_input(self, terminal_id: str, message: str) -> None:
        r = self._client.post(
            f"/terminals/{terminal_id}/input",
            params={"message": message},
        )
        r.raise_for_status()

    def get_status(self, terminal_id: str) -> str:
        r = self._client.get(f"/terminals/{terminal_id}")
        r.raise_for_status()
        return r.json().get("status", "unknown")

    def get_last_output(self, terminal_id: str) -> str:
        r = self._client.get(
            f"/terminals/{terminal_id}/output",
            params={"mode": "last"},
        )
        r.raise_for_status()
        return r.json().get("output", "")

    def exit_terminal(self, terminal_id: str) -> None:
        try:
            r = self._client.post(f"/terminals/{terminal_id}/exit")
            r.raise_for_status()
        except httpx.HTTPError:
            pass

    def close(self) -> None:
        self._client.close()


api = ApiClient(API)


# ── 5. File handoff functions ───────────────────────────────────────────────


def response_path_for(role: str) -> Path:
    return RESPONSE_DIR / RESPONSE_FILES[role]


def clear_stale_response(role: str) -> None:
    p = response_path_for(role)
    if p.exists():
        p.unlink()


def ensure_response_dir() -> None:
    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)


def response_file_instruction(role: str) -> str:
    p = response_path_for(role)
    quoted = shlex.quote(str(p))
    return (
        "\n\n--- RESPONSE FILE INSTRUCTION ---\n"
        "After you finish your analysis, write your COMPLETE final response "
        f"(everything from the summary marker onward) to this file:\n{p}\n"
        f"Use a single shell command:\n"
        f"cat << 'AGENT_EOF' > {quoted}\n"
        "...your full response...\n"
        "AGENT_EOF\n"
        "This is MANDATORY. The orchestrator reads your response from this file.\n"
        "--- END RESPONSE FILE INSTRUCTION ---"
    )


def wait_for_response_file(
    role: str,
    terminal_id: str,
    timeout: int = RESPONSE_TIMEOUT,
) -> str:
    """Poll until response file appears AND terminal is idle/completed.

    When STRICT_FILE_HANDOFF is True (default), raises RuntimeError if the
    file never appears — ensuring file-only handoff with no terminal output
    parsing. When False, falls back to api.get_last_output().

    Early exit: if the terminal has been idle/completed for IDLE_GRACE_SECONDS
    without the response file appearing, stops waiting immediately instead of
    waiting for the full timeout.
    """
    p = response_path_for(role)
    start = time.monotonic()
    idle_since: float | None = None

    while True:
        status = api.get_status(terminal_id)

        if status == "error":
            raise RuntimeError(f"Terminal {terminal_id} entered ERROR state")

        if p.exists() and status in ("idle", "completed"):
            content = p.read_text(encoding="utf-8").strip()
            p.unlink(missing_ok=True)
            if content:
                return content
            # File was empty — fall through to timeout/fallback logic

        # Track how long the terminal has been idle without a response file
        if status in ("idle", "completed") and not p.exists():
            if idle_since is None:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since > IDLE_GRACE_SECONDS:
                if STRICT_FILE_HANDOFF:
                    raise RuntimeError(
                        f"[{role}] Agent finished (idle {IDLE_GRACE_SECONDS}s) "
                        f"but did not write response file "
                        f"(STRICT_FILE_HANDOFF=1, no fallback)"
                    )
                log(f"[{role}] Agent finished but no response file after "
                    f"{IDLE_GRACE_SECONDS}s idle, falling back to get_last_output()")
                return api.get_last_output(terminal_id)
        else:
            idle_since = None  # Reset if terminal is processing or file appeared

        elapsed = time.monotonic() - start
        if elapsed > timeout:
            if status in ("idle", "completed"):
                if STRICT_FILE_HANDOFF:
                    raise RuntimeError(
                        f"[{role}] Response file not written after {timeout}s "
                        f"(STRICT_FILE_HANDOFF=1, no fallback)"
                    )
                log(f"[{role}] Response file not found after {timeout}s, "
                    f"falling back to get_last_output()")
                return api.get_last_output(terminal_id)
            raise TimeoutError(
                f"Timeout ({timeout}s) waiting for {role} response "
                f"(terminal {terminal_id}, status={status})"
            )

        time.sleep(POLL_SECONDS)


def send_and_wait(terminal_id: str, role: str, message: str) -> str:
    """Clear stale file, send prompt, wait for response file."""
    clear_stale_response(role)
    api.send_input(terminal_id, message)
    return wait_for_response_file(role, terminal_id)


# ── 6. Review / approval logic ─────────────────────────────────────────────

ANALYST_EVIDENCE_PATTERNS = [
    # Artifact/spec term + verdict (e.g., "proposal verified", "spec incomplete")
    re.compile(r"(artifact|proposal|design|tasks|spec)\w*\s.{0,30}(verified|missing|incomplete|correct|present|created|updated)", re.IGNORECASE),
    # Priority/traceability + coverage language (e.g., "P1 coverage gap", "traceability confirmed")
    re.compile(r"(P[1-4]|traceability|phase)\w*\s.{0,30}(coverage|gap|confirmed|traced|missing|complete)", re.IGNORECASE),
    # Downstream/contract + specific module or file reference
    re.compile(r"(downstream|contract)\w*\s.{0,40}(\w+\.\w{2,4}|module|service|component|endpoint)", re.IGNORECASE),
    # Handoff + concrete next-step language
    re.compile(r"(handoff|action\s?item)\w*\s.{0,30}(\d+\s*(action|step|item|concrete)|includes|contains|lists)", re.IGNORECASE),
]

PROGRAMMER_EVIDENCE_PATTERNS = [
    re.compile(r"implementation|code|task|change|diff|file", re.IGNORECASE),
    re.compile(r"validation|test|command|run|not_run|pytest|conda", re.IGNORECASE),
    re.compile(r"risk|regression|quality|coverage|evidence", re.IGNORECASE),
    re.compile(r"fix|issue|defect|gap|failure", re.IGNORECASE),
]


def is_review_approved(review_text: str, review_cycle: int, review_role: str) -> bool:
    if not APPROVED_REVIEW_RE.search(review_text):
        return False

    if review_cycle < MIN_REVIEW_CYCLES_BEFORE_APPROVAL:
        return False

    if not REQUIRE_REVIEW_EVIDENCE:
        return True

    notes = _extract_section(review_text, r"^\s*REVIEW_NOTES:")
    if not notes.strip():
        return False

    patterns = (
        ANALYST_EVIDENCE_PATTERNS
        if review_role == "analyst"
        else PROGRAMMER_EVIDENCE_PATTERNS
    )
    hits = sum(1 for p in patterns if p.search(notes))
    return hits >= REVIEW_EVIDENCE_MIN_MATCH


# ── 7. Feedback condensation ───────────────────────────────────────────────


def _extract_section(text: str, start_pattern: str, stop_pattern: str | None = None) -> str:
    """Return text from the first line matching start_pattern.

    If stop_pattern is given, stops before the first subsequent line matching it.
    Otherwise returns from start_pattern to end of text.
    """
    lines = text.splitlines()
    start_re = re.compile(start_pattern, re.IGNORECASE)
    stop_re = re.compile(stop_pattern, re.IGNORECASE) if stop_pattern else None
    start_idx = None
    for i, line in enumerate(lines):
        if start_idx is None:
            if start_re.match(line):
                start_idx = i
        elif stop_re and stop_re.match(line):
            return "\n".join(lines[start_idx:i])
    if start_idx is not None:
        return "\n".join(lines[start_idx:])
    return ""


def extract_review_notes(review_text: str) -> str:
    if not CONDENSE_REVIEW_FEEDBACK:
        return review_text
    condensed = _extract_section(review_text, r"^\s*REVIEW_NOTES:")
    lines = condensed.splitlines()[:MAX_FEEDBACK_LINES]
    if not "".join(lines).strip():
        lines = review_text.splitlines()[:MAX_FEEDBACK_LINES]
    return "\n".join(lines)


def extract_test_evidence(test_text: str) -> str:
    if not CONDENSE_REVIEW_FEEDBACK:
        return test_text
    # Grab RESULT: line + EVIDENCE: section
    result_lines = []
    evidence_section = ""
    for line in test_text.splitlines():
        if re.match(r"^\s*RESULT:", line, re.IGNORECASE):
            result_lines.append(line)
    evidence_section = _extract_section(test_text, r"^\s*EVIDENCE:")
    combined = "\n".join(result_lines)
    if evidence_section:
        combined += "\n" + evidence_section
    lines = combined.splitlines()[:MAX_FEEDBACK_LINES]
    if not "".join(lines).strip():
        lines = test_text.splitlines()[:MAX_FEEDBACK_LINES]
    return "\n".join(lines)


# ── 7b. Cross-phase condensation ────────────────────────────────────────────


def condense_analyst_for_programmer(analyst_out: str) -> str:
    """Condense analyst output to handoff-only for programmer (cross-phase).

    Extracts bounded sections for OpenSpec artifacts, Implementation notes,
    and Risks/assumptions. Falls back to head-truncated text if markers missing.
    """
    if not CONDENSE_CROSS_PHASE:
        return analyst_out
    sections = []
    for label, stop in [
        (r"^\s*-?\s*OpenSpec artifacts", r"^\s*-?\s*Implementation notes"),
        (r"^\s*-?\s*Implementation notes", r"^\s*-?\s*Risks"),
        (r"^\s*-?\s*Risks", r"^\s*-?\s*Downstream impact"),
    ]:
        chunk = _extract_section(analyst_out, label, stop)
        if chunk.strip():
            sections.append(chunk)
    if not sections:
        return "\n".join(analyst_out.splitlines()[:MAX_CROSS_PHASE_LINES])
    combined = "\n".join(sections)
    return "\n".join(combined.splitlines()[:MAX_CROSS_PHASE_LINES])


def condense_programmer_for_tester(programmer_out: str) -> str:
    """Condense programmer output to changes-only for tester (cross-phase).

    Extracts bounded 'Files changed:' and 'Behavior implemented:' sections.
    Falls back to head-truncated text if markers are missing.
    """
    if not CONDENSE_CROSS_PHASE:
        return programmer_out
    sections = []
    files_changed = _extract_section(
        programmer_out, r"^\s*-?\s*Files changed", r"^\s*-?\s*Behavior implemented"
    )
    if files_changed.strip():
        sections.append(files_changed)
    behavior = _extract_section(
        programmer_out, r"^\s*-?\s*Behavior implemented", r"^\s*-?\s*Known limitations"
    )
    if behavior.strip():
        sections.append(behavior)
    if not sections:
        return "\n".join(programmer_out.splitlines()[:MAX_CROSS_PHASE_LINES])
    combined = "\n".join(sections)
    return "\n".join(combined.splitlines()[:MAX_CROSS_PHASE_LINES])


# ── 8. Explore condensation ────────────────────────────────────────────────

_explore_sent: set[str] = set()


def explore_block_for(terminal_id: str) -> str:
    global _explore_sent
    if CONDENSE_EXPLORE_ON_REPEAT and terminal_id in _explore_sent:
        return (
            f"{EXPLORE_HEADER}\n"
            "(Same as initial turn -- refer to your conversation history.)"
        )
    _explore_sent.add(terminal_id)
    return f"{EXPLORE_HEADER}\n{EXPLORE_SUMMARY}"


# ── 9. Prompt builders ─────────────────────────────────────────────────────


def _test_command_instruction() -> str:
    if PROJECT_TEST_CMD.strip():
        return f"Use this project test command when validating locally: {PROJECT_TEST_CMD}"
    return "Use project-specific test command from AGENTS.md (do not assume plain pytest)."


def build_analyst_prompt(round_num: int, analyst_cycle: int) -> str:
    parts = [
        explore_block_for(terminal_ids["analyst"]),
        "",
        f"Round: {round_num}",
        f"Analyst review cycle: {analyst_cycle}",
        "Latest tester feedback:",
        feedback,
        "Latest peer analyst feedback:",
        analyst_feedback,
        "",
        "Guard lines:",
        "system anaylist: dont do testing, dont implement code",
        "",
        "Task:",
        "1) Explore the codebase.",
        "2) Create/update all OpenSpec artifacts using ff command.",
        "3) Return ANALYST_SUMMARY exactly as profile format.",
        "4) Include mandatory sections in ANALYST_SUMMARY:",
        "   - Artifact review per file: proposal.md, design.md, tasks.md, specs/* (PASS|REVISE + evidence).",
        "   - P1-P4 traceability: map each scenario requirement to artifact sections.",
        "   - Phased delivery coverage: phase-by-phase completeness/gaps.",
        "   - Downstream contract impact: planner/API/converter/revised_document implications.",
        "   - Explicit handoff: concrete actions for programmer.",
        response_file_instruction("analyst"),
    ]
    return "\n".join(parts)


def build_analyst_review_prompt(analyst_out: str) -> str:
    parts = [
        explore_block_for(terminal_ids["peer_analyst"]),
        "",
        "System analyst output to review:",
        analyst_out,
        "",
        "Guard lines:",
        "peer system analyst: review only, dont do testing, dont implement code",
        "",
        "Task: Your default stance is REVISE. Only approve when ALL criteria below pass.",
        "",
        "Rejection criteria — REVISE if ANY fail:",
        "1. Scope: must reference specific file paths or module names. Reject if vague.",
        "2. OpenSpec artifacts: must list artifact filenames (proposal.md, design.md, etc). Reject if none listed.",
        "3. Implementation notes: must contain at least 3 concrete action items. Reject if vague or fewer than 3.",
        "4. Risks/assumptions: must not be 'none' or single-line without mitigation. Reject if missing or unmitigated.",
        "5. Downstream impact: must not be 'N/A' or missing. Reject if absent.",
        "",
        "Codebase verification: pick at least 2 file paths from the analyst output and verify they exist using ls. Report what you checked.",
        "",
        "Return REVIEW_RESULT: APPROVED or REVIEW_RESULT: REVISE with REVIEW_NOTES covering each criterion.",
        response_file_instruction("analyst_review"),
    ]
    return "\n".join(parts)


def build_programmer_prompt(
    round_num: int,
    programmer_cycle: int,
    analyst_out: str,
) -> str:
    if CONDENSE_UPSTREAM_ON_REPEAT and programmer_cycle > 1:
        analyst_block = "(Same analyst output as previous cycle -- refer to conversation history.)"
    else:
        analyst_block = condense_analyst_for_programmer(analyst_out)

    parts = [
        explore_block_for(terminal_ids["programmer"]),
        "",
        "System analyst handoff:",
        analyst_block,
        "",
        f"Programmer review cycle: {programmer_cycle}",
        "Latest peer programmer feedback:",
        programmer_feedback,
        "",
        "Guard lines:",
        "programmer: dont do scenario test",
        "Autonomy rules: do not run destructive commands in repo paths (rm, git clean, git reset --hard, overwrite moves)",
        "Autonomy rules: do not delete tests/fixtures/**",
        "Autonomy rules: write temporary artifacts only under .tmp/ or /tmp/",
        "",
        "Task:",
        "1) Apply OpenSpec changes using openspec-apply-change skill.",
        "2) Implement required code changes.",
        "3) Return PROGRAMMER_SUMMARY exactly as profile format.",
        "4) For optional local validation, do not assume plain pytest.",
        f"5) {_test_command_instruction()}",
        response_file_instruction("programmer"),
    ]
    return "\n".join(parts)


def build_programmer_review_prompt(programmer_out: str) -> str:
    parts = [
        explore_block_for(terminal_ids["peer_programmer"]),
        "",
        "Programmer output to review:",
        programmer_out,
        "",
        "Guard lines:",
        "peer programmer: review only, dont do scenario test, dont implement code",
        "peer programmer: enforce non-destructive repo operations and no fixture deletion",
        "",
        "Task:",
        "Review implementation completeness and quality.",
        "Do not require plain pytest command.",
        _test_command_instruction(),
        "If no runnable command exists, report Validation run status: NOT_RUN with reason and continue review.",
        "Return REVIEW_RESULT: APPROVED or REVIEW_RESULT: REVISE with REVIEW_NOTES.",
        response_file_instruction("programmer_review"),
    ]
    return "\n".join(parts)


def build_tester_prompt(programmer_out: str) -> str:
    parts = [
        f"{SCENARIO_HEADER}",
        SCENARIO_TEST,
        "",
        "Programmer changes:",
        condense_programmer_for_tester(programmer_out),
        "",
        "Guard lines:",
        "tester: dont implement code, dont modify openspec artifact",
        "",
        "Task:",
        "1) Run tests based on SCENARIO TEST only.",
        "2) Return strict machine-readable result:",
        "RESULT: PASS or RESULT: FAIL",
        "EVIDENCE:",
        "- Commands run:",
        "- Key outputs:",
        "- Failed criteria (if any):",
        "- Recommended next fix:",
        response_file_instruction("tester"),
    ]
    return "\n".join(parts)


# ── 10. State management ───────────────────────────────────────────────────

session_name: str = ""
terminal_ids: dict[str, str] = {
    "analyst": "",
    "peer_analyst": "",
    "programmer": "",
    "peer_programmer": "",
    "tester": "",
}
current_round: int = 1
current_phase: str = PHASE_ANALYST
final_status: str = "RUNNING"
feedback: str = "None yet."
analyst_feedback: str = "None yet."
programmer_feedback: str = "None yet."
outputs: dict[str, str] = {
    "analyst": "",
    "analyst_review": "",
    "programmer": "",
    "programmer_review": "",
    "tester": "",
}


def save_state() -> None:
    state_path = Path(STATE_FILE)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api": API,
        "provider": PROVIDER,
        "wd": WD,
        "prompt": PROMPT,
        "current_round": current_round,
        "current_phase": current_phase,
        "final_status": final_status,
        "session_name": session_name,
        "terminals": {
            "analyst": terminal_ids["analyst"],
            "peer_analyst": terminal_ids["peer_analyst"],
            "programmer": terminal_ids["programmer"],
            "peer_programmer": terminal_ids["peer_programmer"],
            "tester": terminal_ids["tester"],
        },
        "feedback": feedback,
        "analyst_feedback": analyst_feedback,
        "programmer_feedback": programmer_feedback,
        "outputs": {
            "analyst": outputs["analyst"],
            "analyst_review": outputs["analyst_review"],
            "programmer": outputs["programmer"],
            "programmer_review": outputs["programmer_review"],
            "tester": outputs["tester"],
        },
    }
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def load_state() -> bool:
    global session_name, current_round, current_phase, final_status
    global feedback, analyst_feedback, programmer_feedback

    state_path = Path(STATE_FILE)
    if not state_path.is_file():
        return False

    data = json.loads(state_path.read_text(encoding="utf-8"))

    session_name = data.get("session_name", "")
    terminals = data.get("terminals", {})
    terminal_ids["analyst"] = terminals.get("analyst", "")
    terminal_ids["peer_analyst"] = terminals.get("peer_analyst", "")
    terminal_ids["programmer"] = terminals.get("programmer", "")
    terminal_ids["peer_programmer"] = terminals.get("peer_programmer", "")
    terminal_ids["tester"] = terminals.get("tester", "")

    current_round = data.get("current_round", 1)
    if not isinstance(current_round, int):
        try:
            current_round = int(current_round)
        except (TypeError, ValueError):
            current_round = 1

    current_phase = data.get("current_phase", PHASE_ANALYST)
    if current_phase not in (PHASE_ANALYST, PHASE_PROGRAMMER, PHASE_TESTER, PHASE_DONE):
        current_phase = PHASE_ANALYST

    final_status = data.get("final_status", "RUNNING")
    feedback = data.get("feedback", "None yet.")
    analyst_feedback = data.get("analyst_feedback", "None yet.")
    programmer_feedback = data.get("programmer_feedback", "None yet.")

    out = data.get("outputs", {})
    outputs["analyst"] = out.get("analyst", "")
    outputs["analyst_review"] = out.get("analyst_review", "")
    outputs["programmer"] = out.get("programmer", "")
    outputs["programmer_review"] = out.get("programmer_review", "")
    outputs["tester"] = out.get("tester", "")

    return True


# ── 11. Init / resume logic ────────────────────────────────────────────────


def log_terminal_ids() -> None:
    log(f"SESSION_NAME={session_name}")
    for role, tid in terminal_ids.items():
        log(f"  {role}={tid}")


def init_new_run() -> None:
    global session_name, current_round, current_phase, final_status
    global feedback, analyst_feedback, programmer_feedback

    result = api.create_session("system_analyst")
    terminal_ids["analyst"] = result["id"]
    session_name = result["session_name"]

    for role, profile in [
        ("peer_analyst", "peer_system_analyst"),
        ("programmer", "programmer"),
        ("peer_programmer", "peer_programmer"),
        ("tester", "tester"),
    ]:
        result = api.create_terminal(session_name, profile)
        terminal_ids[role] = result["id"]

    current_round = 1
    current_phase = PHASE_ANALYST
    final_status = "RUNNING"
    feedback = "None yet."
    analyst_feedback = "None yet."
    programmer_feedback = "None yet."
    for key in outputs:
        outputs[key] = ""

    save_state()
    log(f"Initialized new run. State file: {STATE_FILE}")
    log_terminal_ids()


def should_auto_resume(state_file: str) -> bool:
    """Check if state file exists with RUNNING status (for auto-resume)."""
    sp = Path(state_file)
    if not sp.is_file():
        return False
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        return data.get("final_status") == "RUNNING"
    except (json.JSONDecodeError, OSError):
        return False


def verify_resume_terminals() -> None:
    for role, tid in terminal_ids.items():
        if not tid:
            print(f"Cannot resume: missing terminal ID for '{role}' in state file ({STATE_FILE}).", file=sys.stderr)
            sys.exit(1)
        try:
            api.get_status(tid)
        except httpx.HTTPError:
            print(f"Cannot resume: terminal '{tid}' ({role}) is unreachable from API '{API}'.", file=sys.stderr)
            sys.exit(1)


# ── 12. Main loop + cleanup + entry point ──────────────────────────────────


def cleanup(_save: bool = True) -> None:
    if _save:
        try:
            save_state()
        except Exception:
            pass

    if not CLEANUP_ON_EXIT:
        return

    for tid in terminal_ids.values():
        if tid:
            api.exit_terminal(tid)


def _signal_handler(signum: int, _frame: object) -> None:
    sig_name = signal.Signals(signum).name
    log(f"Caught {sig_name}, saving state and cleaning up...")
    cleanup()
    sys.exit(128 + signum)


def main() -> None:
    global PROMPT, EXPLORE_SUMMARY, SCENARIO_TEST
    global current_round, current_phase, final_status
    global feedback, analyst_feedback, programmer_feedback

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # ── Determine resume mode (before prompt loading) ─────────────────
    resume_requested = RESUME
    if not resume_requested and should_auto_resume(STATE_FILE):
        log(f"Auto-resume: found in-progress state file at {STATE_FILE}")
        resume_requested = True

    # ── Load prompt ─────────────────────────────────────────────────────
    if PROMPT_FILE:
        pf = Path(PROMPT_FILE)
        if not pf.is_file():
            print(f"PROMPT_FILE not found: {PROMPT_FILE}", file=sys.stderr)
            sys.exit(1)
        PROMPT = pf.read_text(encoding="utf-8")

    if not PROMPT.strip() and resume_requested:
        sp = Path(STATE_FILE)
        if sp.is_file():
            data = json.loads(sp.read_text(encoding="utf-8"))
            PROMPT = data.get("prompt", "")
            if PROMPT.strip():
                log("Loaded PROMPT from STATE_FILE for resume.")

    if not PROMPT.strip():
        print("PROMPT is empty. Set PROMPT or PROMPT_FILE.", file=sys.stderr)
        sys.exit(1)

    # ── Validate prompt structure ───────────────────────────────────────
    if EXPLORE_HEADER not in PROMPT.splitlines():
        print(f"PROMPT must include header: {EXPLORE_HEADER}", file=sys.stderr)
        sys.exit(1)
    if SCENARIO_HEADER not in PROMPT.splitlines():
        print(f"PROMPT must include header: {SCENARIO_HEADER}", file=sys.stderr)
        sys.exit(1)

    EXPLORE_SUMMARY = _extract_prompt_section(PROMPT, EXPLORE_HEADER, SCENARIO_HEADER)
    SCENARIO_TEST = _extract_prompt_section(PROMPT, SCENARIO_HEADER)

    if not EXPLORE_SUMMARY.strip():
        print("ORIGINAL EXPLORE SUMMARY section is empty.", file=sys.stderr)
        sys.exit(1)
    if not SCENARIO_TEST.strip():
        print("SCENARIO TEST section is empty.", file=sys.stderr)
        sys.exit(1)

    # ── Ensure response directory ───────────────────────────────────────
    ensure_response_dir()

    # ── Init or resume ──────────────────────────────────────────────────
    if resume_requested:
        if not load_state():
            print(f"RESUME requested but no state file found: {STATE_FILE}", file=sys.stderr)
            sys.exit(1)
        verify_resume_terminals()
        log(f"Resuming from state file: {STATE_FILE} (round={current_round} phase={current_phase})")
        log_terminal_ids()
    else:
        init_new_run()

    if current_phase == PHASE_DONE:
        log(f"State already completed (FINAL_STATUS={final_status}). Set RESUME=0 to start a new run.")
        sys.exit(0 if final_status == "PASS" else 1)

    # ── Main orchestration loop ─────────────────────────────────────────
    while current_round <= MAX_ROUNDS:
        rnd = current_round
        print()
        log(f"=== ROUND {rnd} ===")

        # ── ANALYST phase ───────────────────────────────────────────────
        if current_phase == PHASE_ANALYST:
            if not analyst_feedback.strip():
                analyst_feedback = "None yet."
            outputs["analyst"] = ""
            outputs["analyst_review"] = ""
            save_state()

            analyst_approved = False
            for analyst_cycle in range(1, MAX_REVIEW_CYCLES + 1):
                log(f"[round {rnd}] system_analyst: cycle {analyst_cycle} - exploring and updating openspec")
                msg = build_analyst_prompt(rnd, analyst_cycle)
                outputs["analyst"] = send_and_wait(terminal_ids["analyst"], "analyst", msg)
                save_state()

                log(f"[round {rnd}] peer_system_analyst: cycle {analyst_cycle} - reviewing analyst output")
                review_msg = build_analyst_review_prompt(outputs["analyst"])
                outputs["analyst_review"] = send_and_wait(
                    terminal_ids["peer_analyst"], "analyst_review", review_msg
                )
                save_state()

                if is_review_approved(outputs["analyst_review"], analyst_cycle, "analyst"):
                    log(f"[round {rnd}] peer_system_analyst: APPROVED")
                    analyst_approved = True
                    analyst_feedback = "None yet."
                    save_state()
                    break

                if APPROVED_REVIEW_RE.search(outputs["analyst_review"]):
                    log(f"[round {rnd}] peer_system_analyst: APPROVED ignored by strict gate (cycle/evidence not sufficient)")

                log(f"[round {rnd}] peer_system_analyst: REVISE")
                analyst_feedback = extract_review_notes(outputs["analyst_review"])
                save_state()

            if not analyst_approved:
                log(f"[round {rnd}] analyst gate: MAX_REVIEW_CYCLES reached, proceeding without approval")
                feedback = (
                    "Peer analyst did not approve after MAX_REVIEW_CYCLES. Latest review:\n"
                    + extract_review_notes(outputs["analyst_review"])
                )
                log(feedback)
                save_state()

            current_phase = PHASE_PROGRAMMER
            if not programmer_feedback.strip():
                programmer_feedback = "None yet."
            save_state()

        # ── PROGRAMMER phase ────────────────────────────────────────────
        if current_phase == PHASE_PROGRAMMER:
            if not outputs["analyst"].strip():
                log(f"[round {rnd}] missing ANALYST_OUT while resuming programmer phase; falling back to analyst phase")
                current_phase = PHASE_ANALYST
                save_state()
                continue

            if not programmer_feedback.strip():
                programmer_feedback = "None yet."
            outputs["programmer"] = ""
            outputs["programmer_review"] = ""
            save_state()

            programmer_approved = False
            for programmer_cycle in range(1, MAX_REVIEW_CYCLES + 1):
                log(f"[round {rnd}] programmer: cycle {programmer_cycle} - applying openspec and implementing")
                msg = build_programmer_prompt(rnd, programmer_cycle, outputs["analyst"])
                outputs["programmer"] = send_and_wait(
                    terminal_ids["programmer"], "programmer", msg
                )
                save_state()

                log(f"[round {rnd}] peer_programmer: cycle {programmer_cycle} - reviewing implementation")
                review_msg = build_programmer_review_prompt(outputs["programmer"])
                outputs["programmer_review"] = send_and_wait(
                    terminal_ids["peer_programmer"], "programmer_review", review_msg
                )
                save_state()

                if is_review_approved(outputs["programmer_review"], programmer_cycle, "programmer"):
                    log(f"[round {rnd}] peer_programmer: APPROVED")
                    programmer_approved = True
                    programmer_feedback = "None yet."
                    save_state()
                    break

                if APPROVED_REVIEW_RE.search(outputs["programmer_review"]):
                    log(f"[round {rnd}] peer_programmer: APPROVED ignored by strict gate (cycle/evidence not sufficient)")

                log(f"[round {rnd}] peer_programmer: REVISE")
                programmer_feedback = extract_review_notes(outputs["programmer_review"])
                save_state()

            if not programmer_approved:
                log(f"[round {rnd}] programmer gate: MAX_REVIEW_CYCLES reached, proceeding without approval")
                feedback = (
                    "Peer programmer did not approve after MAX_REVIEW_CYCLES. Latest review:\n"
                    + extract_review_notes(outputs["programmer_review"])
                )
                log(feedback)
                save_state()

            current_phase = PHASE_TESTER
            save_state()

        # ── TESTER phase ────────────────────────────────────────────────
        if current_phase == PHASE_TESTER:
            if not outputs["programmer"].strip():
                log(f"[round {rnd}] missing PROGRAMMER_OUT while resuming tester phase; falling back to programmer phase")
                current_phase = PHASE_PROGRAMMER
                save_state()
                continue

            log(f"[round {rnd}] tester: running scenario test")
            msg = build_tester_prompt(outputs["programmer"])
            outputs["tester"] = send_and_wait(terminal_ids["tester"], "tester", msg)
            save_state()

            print(outputs["tester"])

            if PASS_RESULT_RE.search(outputs["tester"]):
                current_phase = PHASE_DONE
                final_status = "PASS"
                save_state()
                print()
                log("FINAL: PASS")
                cleanup(_save=False)
                sys.exit(0)

            feedback = extract_test_evidence(outputs["tester"])
            log(f"[round {rnd}] tester: FAIL, retrying with feedback")
            log("FINAL: FAIL (retrying)")

            current_round += 1
            current_phase = PHASE_ANALYST
            analyst_feedback = "None yet."
            programmer_feedback = "None yet."
            for key in outputs:
                outputs[key] = ""
            save_state()

    # ── Max rounds exhausted ────────────────────────────────────────────
    current_phase = PHASE_DONE
    final_status = "FAIL"
    save_state()
    log(f"Reached MAX_ROUNDS={MAX_ROUNDS} without PASS")
    cleanup(_save=False)
    sys.exit(1)


def _extract_prompt_section(text: str, start_header: str, end_header: str | None = None) -> str:
    """Extract content between two header lines (exclusive), like shell's extract_section."""
    lines = text.splitlines()
    capturing = False
    result = []
    for line in lines:
        if line == start_header:
            capturing = True
            continue
        if end_header and line == end_header:
            break
        if capturing:
            result.append(line)
    return "\n".join(result)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        log(f"Fatal error: {exc}")
        cleanup()
        sys.exit(1)
    finally:
        api.close()
