#!/usr/bin/env bash
set -euo pipefail

API="${API:-http://localhost:9889}"
PROVIDER="${PROVIDER:-codex}"
WD="${WD:-$PWD}"
PROMPT="${PROMPT:-}"
PROMPT_FILE="${PROMPT_FILE:-}"
MAX_ROUNDS="${MAX_ROUNDS:-8}"
POLL_SECONDS="${POLL_SECONDS:-2}"
MAX_REVIEW_CYCLES="${MAX_REVIEW_CYCLES:-3}"
HANDOFF_STABLE_POLLS="${HANDOFF_STABLE_POLLS:-2}"
PROJECT_TEST_CMD="${PROJECT_TEST_CMD:-}"
MIN_REVIEW_CYCLES_BEFORE_APPROVAL="${MIN_REVIEW_CYCLES_BEFORE_APPROVAL:-2}"
REQUIRE_REVIEW_EVIDENCE="${REQUIRE_REVIEW_EVIDENCE:-1}"
REVIEW_EVIDENCE_MIN_MATCH="${REVIEW_EVIDENCE_MIN_MATCH:-3}"
RESUME="${RESUME:-0}"
MAX_STRUCTURED_OUTPUT_LINES="${MAX_STRUCTURED_OUTPUT_LINES:-60}"
CONDENSE_EXPLORE_ON_REPEAT="${CONDENSE_EXPLORE_ON_REPEAT:-1}"
CONDENSE_REVIEW_FEEDBACK="${CONDENSE_REVIEW_FEEDBACK:-1}"
MAX_FEEDBACK_LINES="${MAX_FEEDBACK_LINES:-30}"
CONDENSE_UPSTREAM_ON_REPEAT="${CONDENSE_UPSTREAM_ON_REPEAT:-1}"
STATE_FILE="${STATE_FILE:-$WD/.tmp/codex-3agents-loop-state.json}"
CLEANUP_ON_EXIT="${CLEANUP_ON_EXIT:-0}"
EXPLORE_HEADER="*** ORIGINAL EXPLORE SUMMARY ***"
SCENARIO_HEADER="*** SCENARIO TEST ***"
ANALYST_SUMMARY_REGEX='(^|[^[:alnum:]_])ANALYST_SUMMARY([^[:alnum:]_]|$)'
PROGRAMMER_SUMMARY_REGEX='(^|[^[:alnum:]_])PROGRAMMER_SUMMARY([^[:alnum:]_]|$)'
REVIEW_RESULT_REGEX='^[[:space:]]*REVIEW_RESULT:[[:space:]]*(APPROVED|REVISE)\b'
TEST_RESULT_REGEX='^[[:space:]]*RESULT:[[:space:]]*(PASS|FAIL)\b'
PASS_RESULT_REGEX='^[[:space:]]*RESULT:[[:space:]]*PASS\b'
APPROVED_REVIEW_REGEX='^[[:space:]]*REVIEW_RESULT:[[:space:]]*APPROVED\b'

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing command: $1" >&2; exit 1; }
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

require_cmd curl
require_cmd jq
require_cmd grep

_EXPLORE_SENT_LIST=""

explore_block_for() {
  local terminal_id="$1"
  if [[ "$CONDENSE_EXPLORE_ON_REPEAT" == "1" ]] && echo "$_EXPLORE_SENT_LIST" | grep -qF "|$terminal_id|"; then
    printf '%s\n' \
      "*** ORIGINAL EXPLORE SUMMARY ***" \
      "(Same as initial turn -- refer to your conversation history.)"
  else
    _EXPLORE_SENT_LIST="${_EXPLORE_SENT_LIST}|${terminal_id}|"
    printf '%s\n' \
      "*** ORIGINAL EXPLORE SUMMARY ***" \
      "$EXPLORE_SUMMARY"
  fi
}

extract_review_notes() {
  local review_text="$1"
  if [[ "$CONDENSE_REVIEW_FEEDBACK" != "1" ]]; then
    printf '%s\n' "$review_text"; return
  fi
  local condensed
  condensed="$(printf '%s\n' "$review_text" | sed -n '/^[[:space:]]*REVIEW_NOTES:/,$p' | head -n "$MAX_FEEDBACK_LINES")"
  if [[ -z "${condensed//[[:space:]]/}" ]]; then
    printf '%s\n' "$review_text" | head -n "$MAX_FEEDBACK_LINES"
  else
    printf '%s\n' "$condensed"
  fi
}

extract_test_evidence() {
  local test_text="$1"
  if [[ "$CONDENSE_REVIEW_FEEDBACK" != "1" ]]; then
    printf '%s\n' "$test_text"; return
  fi
  local condensed
  condensed="$(printf '%s\n' "$test_text" | sed -n '/^[[:space:]]*RESULT:/p; /^[[:space:]]*EVIDENCE:/,$p' | head -n "$MAX_FEEDBACK_LINES")"
  if [[ -z "${condensed//[[:space:]]/}" ]]; then
    printf '%s\n' "$test_text" | head -n "$MAX_FEEDBACK_LINES"
  else
    printf '%s\n' "$condensed"
  fi
}

if [[ -n "$PROMPT_FILE" ]]; then
  if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "PROMPT_FILE not found: $PROMPT_FILE" >&2
    exit 1
  fi
  PROMPT="$(cat "$PROMPT_FILE")"
fi

if [[ -z "${PROMPT//[[:space:]]/}" ]] && [[ "$RESUME" == "1" ]] && [[ -f "$STATE_FILE" ]]; then
  PROMPT="$(jq -r '.prompt // empty' "$STATE_FILE")"
  if [[ -n "${PROMPT//[[:space:]]/}" ]]; then
    log "Loaded PROMPT from STATE_FILE for resume."
  fi
fi

if [[ -z "${PROMPT//[[:space:]]/}" ]]; then
  echo "PROMPT is empty. Set PROMPT or PROMPT_FILE." >&2
  exit 1
fi

extract_section() {
  local input="$1"
  local start_header="$2"
  local end_header="${3:-}"

  if [[ -n "$end_header" ]]; then
    awk -v start="$start_header" -v end="$end_header" '
      $0 == start {capture=1; next}
      $0 == end {capture=0}
      capture {print}
    ' <<<"$input"
  else
    awk -v start="$start_header" '
      $0 == start {capture=1; next}
      capture {print}
    ' <<<"$input"
  fi
}

validate_prompt_structure() {
  if ! grep -Fqx "$EXPLORE_HEADER" <<<"$PROMPT"; then
    echo "PROMPT must include header: $EXPLORE_HEADER" >&2
    exit 1
  fi
  if ! grep -Fqx "$SCENARIO_HEADER" <<<"$PROMPT"; then
    echo "PROMPT must include header: $SCENARIO_HEADER" >&2
    exit 1
  fi
}

validate_prompt_structure

EXPLORE_SUMMARY="$(extract_section "$PROMPT" "$EXPLORE_HEADER" "$SCENARIO_HEADER")"
SCENARIO_TEST="$(extract_section "$PROMPT" "$SCENARIO_HEADER")"

if [[ -z "${EXPLORE_SUMMARY//[[:space:]]/}" ]]; then
  echo "ORIGINAL EXPLORE SUMMARY section is empty." >&2
  exit 1
fi

if [[ -z "${SCENARIO_TEST//[[:space:]]/}" ]]; then
  echo "SCENARIO TEST section is empty." >&2
  exit 1
fi

test_command_instruction() {
  if [[ -n "${PROJECT_TEST_CMD//[[:space:]]/}" ]]; then
    printf 'Use this project test command when validating locally: %s' "$PROJECT_TEST_CMD"
  else
    printf 'Use project-specific test command from AGENTS.md (do not assume plain pytest).'
  fi
}

create_session() {
  local profile="$1"
  curl -fsS -X POST "$API/sessions" --get \
    --data-urlencode "provider=$PROVIDER" \
    --data-urlencode "agent_profile=$profile" \
    --data-urlencode "working_directory=$WD"
}

create_terminal() {
  local session_name="$1"
  local profile="$2"
  curl -fsS -X POST "$API/sessions/$session_name/terminals" --get \
    --data-urlencode "provider=$PROVIDER" \
    --data-urlencode "agent_profile=$profile" \
    --data-urlencode "working_directory=$WD"
}

send_input() {
  local terminal_id="$1"
  local message="$2"
  curl -fsS -X POST "$API/terminals/$terminal_id/input" --get \
    --data-urlencode "message=$message" >/dev/null
}

get_status() {
  local terminal_id="$1"
  curl -fsS "$API/terminals/$terminal_id" | jq -r '.status'
}

wait_for_terminal() {
  local terminal_id="$1"
  local timeout_seconds="${2:-1800}"
  local start now status
  start="$(date +%s)"

  while true; do
    status="$(get_status "$terminal_id")"
    case "$status" in
      idle|completed) return 0 ;;
      error) echo "Terminal $terminal_id entered ERROR state" >&2; return 1 ;;
    esac
    now="$(date +%s)"
    if (( now - start > timeout_seconds )); then
      echo "Timeout waiting for terminal $terminal_id" >&2
      return 1
    fi
    sleep "$POLL_SECONDS"
  done
}

get_last_output() {
  local terminal_id="$1"
  curl -fsS "$API/terminals/$terminal_id/output?mode=last" | jq -r '.output'
}

get_structured_output() {
  local terminal_id="$1"
  local marker_regex="$2"
  local max_lines="${3:-$MAX_STRUCTURED_OUTPUT_LINES}"
  local full_output line_no

  full_output="$(
    curl -fsS "$API/terminals/$terminal_id/output?mode=full" | jq -r '.output' \
      | sed -E $'s/\x1B\\[[0-9;?]*[ -/]*[@-~]//g' \
      | tr -d '\r'
  )"

  line_no="$(printf '%s\n' "$full_output" | grep -En "$marker_regex" | tail -n 1 | cut -d: -f1 || true)"
  if [[ -z "$line_no" ]]; then
    get_last_output "$terminal_id" | tail -n "$max_lines"
    return
  fi

  printf '%s\n' "$full_output" | tail -n +"$line_no" | awk -v maxlines="$max_lines" '
    NR == 1 { print; next }
    /^[[:space:]]*$/ { exit }
    /^[[:space:]]*›[[:space:]]*/ { exit }
    /^[[:space:]]*\?[[:space:]]*for shortcuts/ { exit }
    /^[[:space:]]*.*[0-9]+%[[:space:]]+context left[[:space:]]*$/ { exit }
    { print }
    maxlines > 0 && NR >= maxlines { exit }
  '
}

wait_for_expected_output() {
  local terminal_id="$1"
  local previous_output="$2"
  local expected_regex="$3"
  local timeout_seconds="${4:-1800}"
  local start now status current_output
  local stable_count=0
  local stable_candidate=""
  start="$(date +%s)"

  while true; do
    status="$(get_status "$terminal_id")"
    current_output="$(get_structured_output "$terminal_id" "$expected_regex" 2>/dev/null || true)"

    if [[ "$status" == "error" ]]; then
      echo "Terminal $terminal_id entered ERROR state" >&2
      return 1
    fi

    if [[ "$current_output" != "$previous_output" ]] && [[ "$status" == "idle" || "$status" == "completed" ]] && echo "$current_output" | grep -Eiq "$expected_regex"; then
      if [[ "$current_output" == "$stable_candidate" ]]; then
        stable_count=$((stable_count + 1))
      else
        stable_candidate="$current_output"
        stable_count=1
      fi

      if (( stable_count >= HANDOFF_STABLE_POLLS )); then
        return 0
      fi
    else
      stable_count=0
      stable_candidate=""
    fi

    now="$(date +%s)"
    if (( now - start > timeout_seconds )); then
      echo "Timeout waiting for expected output from terminal $terminal_id (status=$status, expected=$expected_regex)" >&2
      return 1
    fi

    sleep "$POLL_SECONDS"
  done
}

is_review_approved() {
  local review_text="$1"
  local review_cycle="$2"
  local review_role="$3"
  local notes evidence_hits=0
  local -a evidence_patterns

  if ! echo "$review_text" | grep -Eiq "$APPROVED_REVIEW_REGEX"; then
    return 1
  fi

  if (( review_cycle < MIN_REVIEW_CYCLES_BEFORE_APPROVAL )); then
    return 1
  fi

  if [[ "$REQUIRE_REVIEW_EVIDENCE" != "1" ]]; then
    return 0
  fi

  notes="$(printf '%s\n' "$review_text" | sed -n '/^[[:space:]]*REVIEW_NOTES:/,$p')"
  if [[ -z "${notes//[[:space:]]/}" ]]; then
    return 1
  fi

  if [[ "$review_role" == "analyst" ]]; then
    evidence_patterns=(
      'artifact|proposal|design|tasks|spec'
      'P1|P2|P3|P4|traceability|phase'
      'downstream|contract|planner|api|converter|revised_document'
      'handoff|actionable|concrete|next[[:space:]-]?step'
    )
  else
    evidence_patterns=(
      'implementation|code|task|change|diff|file'
      'validation|test|command|run|not_run|pytest|conda'
      'risk|regression|quality|coverage|evidence'
      'fix|issue|defect|gap|failure'
    )
  fi

  for pattern in "${evidence_patterns[@]}"; do
    if echo "$notes" | grep -Eiq "$pattern"; then
      evidence_hits=$((evidence_hits + 1))
    fi
  done

  if (( evidence_hits >= REVIEW_EVIDENCE_MIN_MATCH )); then
    return 0
  fi

  return 1
}

PHASE_ANALYST="analyst"
PHASE_PROGRAMMER="programmer"
PHASE_TESTER="tester"
PHASE_DONE="done"

SESSION_NAME=""
ANALYST_ID=""
PEER_ANALYST_ID=""
PROGRAMMER_ID=""
PEER_PROGRAMMER_ID=""
TESTER_ID=""

feedback="None yet."
analyst_feedback="None yet."
programmer_feedback="None yet."

ANALYST_OUT=""
ANALYST_REVIEW_OUT=""
PROGRAMMER_OUT=""
PROGRAMMER_REVIEW_OUT=""
TEST_OUT=""

CURRENT_ROUND=1
CURRENT_PHASE="$PHASE_ANALYST"
FINAL_STATUS="RUNNING"

save_state() {
  mkdir -p "$(dirname "$STATE_FILE")"
  jq -n \
    --arg api "$API" \
    --arg provider "$PROVIDER" \
    --arg wd "$WD" \
    --arg prompt "$PROMPT" \
    --arg session_name "$SESSION_NAME" \
    --arg analyst_id "$ANALYST_ID" \
    --arg peer_analyst_id "$PEER_ANALYST_ID" \
    --arg programmer_id "$PROGRAMMER_ID" \
    --arg peer_programmer_id "$PEER_PROGRAMMER_ID" \
    --arg tester_id "$TESTER_ID" \
    --arg current_phase "$CURRENT_PHASE" \
    --arg final_status "$FINAL_STATUS" \
    --arg feedback "$feedback" \
    --arg analyst_feedback "$analyst_feedback" \
    --arg programmer_feedback "$programmer_feedback" \
    --arg analyst_out "$ANALYST_OUT" \
    --arg analyst_review_out "$ANALYST_REVIEW_OUT" \
    --arg programmer_out "$PROGRAMMER_OUT" \
    --arg programmer_review_out "$PROGRAMMER_REVIEW_OUT" \
    --arg test_out "$TEST_OUT" \
    --arg updated_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --argjson current_round "${CURRENT_ROUND:-1}" \
    '{
      version: 1,
      updated_at: $updated_at,
      api: $api,
      provider: $provider,
      wd: $wd,
      prompt: $prompt,
      current_round: $current_round,
      current_phase: $current_phase,
      final_status: $final_status,
      session_name: $session_name,
      terminals: {
        analyst: $analyst_id,
        peer_analyst: $peer_analyst_id,
        programmer: $programmer_id,
        peer_programmer: $peer_programmer_id,
        tester: $tester_id
      },
      feedback: $feedback,
      analyst_feedback: $analyst_feedback,
      programmer_feedback: $programmer_feedback,
      outputs: {
        analyst: $analyst_out,
        analyst_review: $analyst_review_out,
        programmer: $programmer_out,
        programmer_review: $programmer_review_out,
        tester: $test_out
      }
    }' >"$STATE_FILE"
}

load_state() {
  [[ -f "$STATE_FILE" ]] || return 1

  SESSION_NAME="$(jq -r '.session_name // ""' "$STATE_FILE")"
  ANALYST_ID="$(jq -r '.terminals.analyst // ""' "$STATE_FILE")"
  PEER_ANALYST_ID="$(jq -r '.terminals.peer_analyst // ""' "$STATE_FILE")"
  PROGRAMMER_ID="$(jq -r '.terminals.programmer // ""' "$STATE_FILE")"
  PEER_PROGRAMMER_ID="$(jq -r '.terminals.peer_programmer // ""' "$STATE_FILE")"
  TESTER_ID="$(jq -r '.terminals.tester // ""' "$STATE_FILE")"

  CURRENT_ROUND="$(jq -r '.current_round // 1' "$STATE_FILE")"
  CURRENT_PHASE="$(jq -r '.current_phase // "analyst"' "$STATE_FILE")"
  FINAL_STATUS="$(jq -r '.final_status // "RUNNING"' "$STATE_FILE")"

  feedback="$(jq -r '.feedback // "None yet."' "$STATE_FILE")"
  analyst_feedback="$(jq -r '.analyst_feedback // "None yet."' "$STATE_FILE")"
  programmer_feedback="$(jq -r '.programmer_feedback // "None yet."' "$STATE_FILE")"

  ANALYST_OUT="$(jq -r '.outputs.analyst // ""' "$STATE_FILE")"
  ANALYST_REVIEW_OUT="$(jq -r '.outputs.analyst_review // ""' "$STATE_FILE")"
  PROGRAMMER_OUT="$(jq -r '.outputs.programmer // ""' "$STATE_FILE")"
  PROGRAMMER_REVIEW_OUT="$(jq -r '.outputs.programmer_review // ""' "$STATE_FILE")"
  TEST_OUT="$(jq -r '.outputs.tester // ""' "$STATE_FILE")"

  [[ "$CURRENT_ROUND" =~ ^[0-9]+$ ]] || CURRENT_ROUND=1
  case "$CURRENT_PHASE" in
    "$PHASE_ANALYST" | "$PHASE_PROGRAMMER" | "$PHASE_TESTER" | "$PHASE_DONE") ;;
    *) CURRENT_PHASE="$PHASE_ANALYST" ;;
  esac
}

verify_resume_terminals() {
  local terminal_id
  for terminal_id in \
    "$ANALYST_ID" "$PEER_ANALYST_ID" "$PROGRAMMER_ID" "$PEER_PROGRAMMER_ID" "$TESTER_ID"; do
    if [[ -z "$terminal_id" ]]; then
      echo "Cannot resume: missing terminal ID in state file ($STATE_FILE)." >&2
      return 1
    fi
    if ! curl -fsS "$API/terminals/$terminal_id" >/dev/null; then
      echo "Cannot resume: terminal '$terminal_id' is unreachable from API '$API'." >&2
      return 1
    fi
  done
}

log_terminal_ids() {
  log "SESSION_NAME=$SESSION_NAME"
  log "ANALYST_ID=$ANALYST_ID"
  log "PEER_ANALYST_ID=$PEER_ANALYST_ID"
  log "PROGRAMMER_ID=$PROGRAMMER_ID"
  log "PEER_PROGRAMMER_ID=$PEER_PROGRAMMER_ID"
  log "TESTER_ID=$TESTER_ID"
}

init_new_run() {
  local analyst_json peer_analyst_json programmer_json peer_programmer_json tester_json

  analyst_json="$(create_session system_analyst)"
  ANALYST_ID="$(echo "$analyst_json" | jq -r '.id')"
  SESSION_NAME="$(echo "$analyst_json" | jq -r '.session_name')"

  peer_analyst_json="$(create_terminal "$SESSION_NAME" peer_system_analyst)"
  PEER_ANALYST_ID="$(echo "$peer_analyst_json" | jq -r '.id')"

  programmer_json="$(create_terminal "$SESSION_NAME" programmer)"
  PROGRAMMER_ID="$(echo "$programmer_json" | jq -r '.id')"

  peer_programmer_json="$(create_terminal "$SESSION_NAME" peer_programmer)"
  PEER_PROGRAMMER_ID="$(echo "$peer_programmer_json" | jq -r '.id')"

  tester_json="$(create_terminal "$SESSION_NAME" tester)"
  TESTER_ID="$(echo "$tester_json" | jq -r '.id')"

  CURRENT_ROUND=1
  CURRENT_PHASE="$PHASE_ANALYST"
  FINAL_STATUS="RUNNING"
  feedback="None yet."
  analyst_feedback="None yet."
  programmer_feedback="None yet."
  ANALYST_OUT=""
  ANALYST_REVIEW_OUT=""
  PROGRAMMER_OUT=""
  PROGRAMMER_REVIEW_OUT=""
  TEST_OUT=""

  save_state
  log "Initialized new run. State file: $STATE_FILE"
  log_terminal_ids
}

exit_terminal_if_set() {
  local terminal_id="$1"
  if [[ -n "$terminal_id" ]]; then
    curl -fsS -X POST "$API/terminals/$terminal_id/exit" >/dev/null || true
  fi
}

cleanup() {
  save_state || true

  if [[ "$CLEANUP_ON_EXIT" != "1" ]]; then
    return
  fi

  exit_terminal_if_set "$ANALYST_ID"
  exit_terminal_if_set "$PEER_ANALYST_ID"
  exit_terminal_if_set "$PROGRAMMER_ID"
  exit_terminal_if_set "$PEER_PROGRAMMER_ID"
  exit_terminal_if_set "$TESTER_ID"
}
trap cleanup EXIT

if [[ "$RESUME" == "1" ]]; then
  if ! load_state; then
    echo "RESUME=1 but no state file found: $STATE_FILE" >&2
    exit 1
  fi
  verify_resume_terminals
  log "Resuming from state file: $STATE_FILE (round=$CURRENT_ROUND phase=$CURRENT_PHASE)"
  log_terminal_ids
else
  init_new_run
fi

if [[ "$CURRENT_PHASE" == "$PHASE_DONE" ]]; then
  log "State already completed (FINAL_STATUS=$FINAL_STATUS). Set RESUME=0 to start a new run."
  if [[ "$FINAL_STATUS" == "PASS" ]]; then
    exit 0
  fi
  exit 1
fi

while (( CURRENT_ROUND <= MAX_ROUNDS )); do
  round="$CURRENT_ROUND"
  echo
  log "=== ROUND $round ==="

  if [[ "$CURRENT_PHASE" == "$PHASE_ANALYST" ]]; then
    [[ -n "${analyst_feedback//[[:space:]]/}" ]] || analyst_feedback="None yet."
    ANALYST_OUT=""
    ANALYST_REVIEW_OUT=""
    save_state

    ANALYST_APPROVED=0
    for analyst_cycle in $(seq 1 "$MAX_REVIEW_CYCLES"); do
      log "[round $round] system_analyst: cycle $analyst_cycle - exploring and updating openspec"
      ANALYST_MSG="$(printf '%s\n' \
        "$(explore_block_for "$ANALYST_ID")" \
        "" \
        "Round: $round" \
        "Analyst review cycle: $analyst_cycle" \
        "Latest tester feedback:" \
        "$feedback" \
        "Latest peer analyst feedback:" \
        "$analyst_feedback" \
        "" \
        "Guard lines:" \
        "system anaylist: dont do testing, dont implement code" \
        "" \
        "Task:" \
        "1) Explore the codebase." \
        "2) Create/update all OpenSpec artifacts using the OpenSpec fast-forward skill." \
        "3) Return ANALYST_SUMMARY exactly as profile format." \
        "4) Include mandatory sections in ANALYST_SUMMARY:" \
        "   - Artifact review per file: proposal.md, design.md, tasks.md, specs/* (PASS|REVISE + evidence)." \
        "   - P1-P4 traceability: map each scenario requirement to artifact sections." \
        "   - Phased delivery coverage: phase-by-phase completeness/gaps." \
        "   - Downstream contract impact: planner/API/converter/revised_document implications." \
        "   - Explicit handoff: concrete actions for programmer.")"
      ANALYST_BEFORE="$(get_last_output "$ANALYST_ID" 2>/dev/null || true)"
      send_input "$ANALYST_ID" "$ANALYST_MSG"
      wait_for_expected_output "$ANALYST_ID" "$ANALYST_BEFORE" "$ANALYST_SUMMARY_REGEX" 1800
      ANALYST_OUT="$(get_structured_output "$ANALYST_ID" "$ANALYST_SUMMARY_REGEX")"
      save_state

      log "[round $round] peer_system_analyst: cycle $analyst_cycle - reviewing analyst output"
      ANALYST_REVIEW_MSG="$(printf '%s\n' \
        "$(explore_block_for "$PEER_ANALYST_ID")" \
        "" \
        "System analyst output to review:" \
        "$ANALYST_OUT" \
        "" \
        "Guard lines:" \
        "peer system analyst: review only, dont do testing, dont implement code" \
        "" \
        "Task:" \
        "Review analyst output quality and OpenSpec completeness using this checklist:" \
        "- Has per-artifact review with evidence for proposal/design/tasks/specs." \
        "- Has P1-P4 traceability and phased coverage." \
        "- Has downstream contract impact and clear programmer handoff." \
        "Return REVIEW_RESULT: APPROVED or REVIEW_RESULT: REVISE with REVIEW_NOTES.")"
      ANALYST_REVIEW_BEFORE="$(get_structured_output "$PEER_ANALYST_ID" "$REVIEW_RESULT_REGEX" 2>/dev/null || true)"
      send_input "$PEER_ANALYST_ID" "$ANALYST_REVIEW_MSG"
      wait_for_expected_output "$PEER_ANALYST_ID" "$ANALYST_REVIEW_BEFORE" "$REVIEW_RESULT_REGEX" 1800
      ANALYST_REVIEW_OUT="$(get_structured_output "$PEER_ANALYST_ID" "$REVIEW_RESULT_REGEX")"
      save_state

      if is_review_approved "$ANALYST_REVIEW_OUT" "$analyst_cycle" "analyst"; then
        log "[round $round] peer_system_analyst: APPROVED"
        ANALYST_APPROVED=1
        analyst_feedback="None yet."
        save_state
        break
      fi
      if echo "$ANALYST_REVIEW_OUT" | grep -Eiq "$APPROVED_REVIEW_REGEX"; then
        log "[round $round] peer_system_analyst: APPROVED ignored by strict gate (cycle/evidence not sufficient)"
      fi
      log "[round $round] peer_system_analyst: REVISE"
      analyst_feedback="$(extract_review_notes "$ANALYST_REVIEW_OUT")"
      save_state
    done

    if [[ "$ANALYST_APPROVED" -ne 1 ]]; then
      log "[round $round] analyst gate: MAX_REVIEW_CYCLES reached, proceeding without approval"
      feedback="Peer analyst did not approve after MAX_REVIEW_CYCLES. Latest review:\n$(extract_review_notes "$ANALYST_REVIEW_OUT")"
      log "$feedback"
      save_state
    fi

    CURRENT_PHASE="$PHASE_PROGRAMMER"
    [[ -n "${programmer_feedback//[[:space:]]/}" ]] || programmer_feedback="None yet."
    save_state
  fi

  if [[ "$CURRENT_PHASE" == "$PHASE_PROGRAMMER" ]]; then
    if [[ -z "${ANALYST_OUT//[[:space:]]/}" ]]; then
      log "[round $round] missing ANALYST_OUT while resuming programmer phase; falling back to analyst phase"
      CURRENT_PHASE="$PHASE_ANALYST"
      save_state
      continue
    fi

    [[ -n "${programmer_feedback//[[:space:]]/}" ]] || programmer_feedback="None yet."
    PROGRAMMER_OUT=""
    PROGRAMMER_REVIEW_OUT=""
    save_state

    PROGRAMMER_APPROVED=0
    for programmer_cycle in $(seq 1 "$MAX_REVIEW_CYCLES"); do
      log "[round $round] programmer: cycle $programmer_cycle - applying openspec and implementing"
      local analyst_block="$ANALYST_OUT"
      if [[ "$CONDENSE_UPSTREAM_ON_REPEAT" == "1" ]] && (( programmer_cycle > 1 )); then
        analyst_block="(Same analyst output as previous cycle -- refer to conversation history.)"
      fi
      PROGRAMMER_MSG="$(printf '%s\n' \
        "$(explore_block_for "$PROGRAMMER_ID")" \
        "" \
        "System analyst output:" \
        "$analyst_block" \
        "" \
        "Programmer review cycle: $programmer_cycle" \
        "Latest peer programmer feedback:" \
        "$programmer_feedback" \
        "" \
        "Guard lines:" \
        "programmer: dont do scenario test" \
        "Autonomy rules: do not run destructive commands in repo paths (rm, git clean, git reset --hard, overwrite moves)" \
        "Autonomy rules: do not delete tests/fixtures/**" \
        "Autonomy rules: write temporary artifacts only under .tmp/ or /tmp/" \
        "" \
        "Task:" \
        "1) Apply OpenSpec changes using openspec-apply-change skill." \
        "2) Implement required code changes." \
        "3) Return PROGRAMMER_SUMMARY exactly as profile format." \
        "4) For optional local validation, do not assume plain pytest." \
        "5) $(test_command_instruction)")"
      PROGRAMMER_BEFORE="$(get_structured_output "$PROGRAMMER_ID" "$PROGRAMMER_SUMMARY_REGEX" 2>/dev/null || true)"
      send_input "$PROGRAMMER_ID" "$PROGRAMMER_MSG"
      wait_for_expected_output "$PROGRAMMER_ID" "$PROGRAMMER_BEFORE" "$PROGRAMMER_SUMMARY_REGEX" 1800
      PROGRAMMER_OUT="$(get_structured_output "$PROGRAMMER_ID" "$PROGRAMMER_SUMMARY_REGEX")"
      save_state

      log "[round $round] peer_programmer: cycle $programmer_cycle - reviewing implementation"
      PROGRAMMER_REVIEW_MSG="$(printf '%s\n' \
        "$(explore_block_for "$PEER_PROGRAMMER_ID")" \
        "" \
        "Programmer output to review:" \
        "$PROGRAMMER_OUT" \
        "" \
        "Guard lines:" \
        "peer programmer: review only, dont do scenario test, dont implement code" \
        "peer programmer: enforce non-destructive repo operations and no fixture deletion" \
        "" \
        "Task:" \
        "Review implementation completeness and quality." \
        "Do not require plain pytest command." \
        "$(test_command_instruction)" \
        "If no runnable command exists, report Validation run status: NOT_RUN with reason and continue review." \
        "Return REVIEW_RESULT: APPROVED or REVIEW_RESULT: REVISE with REVIEW_NOTES.")"
      PROGRAMMER_REVIEW_BEFORE="$(get_structured_output "$PEER_PROGRAMMER_ID" "$REVIEW_RESULT_REGEX" 2>/dev/null || true)"
      send_input "$PEER_PROGRAMMER_ID" "$PROGRAMMER_REVIEW_MSG"
      wait_for_expected_output "$PEER_PROGRAMMER_ID" "$PROGRAMMER_REVIEW_BEFORE" "$REVIEW_RESULT_REGEX" 1800
      PROGRAMMER_REVIEW_OUT="$(get_structured_output "$PEER_PROGRAMMER_ID" "$REVIEW_RESULT_REGEX")"
      save_state

      if is_review_approved "$PROGRAMMER_REVIEW_OUT" "$programmer_cycle" "programmer"; then
        log "[round $round] peer_programmer: APPROVED"
        PROGRAMMER_APPROVED=1
        programmer_feedback="None yet."
        save_state
        break
      fi
      if echo "$PROGRAMMER_REVIEW_OUT" | grep -Eiq "$APPROVED_REVIEW_REGEX"; then
        log "[round $round] peer_programmer: APPROVED ignored by strict gate (cycle/evidence not sufficient)"
      fi
      log "[round $round] peer_programmer: REVISE"
      programmer_feedback="$(extract_review_notes "$PROGRAMMER_REVIEW_OUT")"
      save_state
    done

    if [[ "$PROGRAMMER_APPROVED" -ne 1 ]]; then
      log "[round $round] programmer gate: MAX_REVIEW_CYCLES reached, proceeding without approval"
      feedback="Peer programmer did not approve after MAX_REVIEW_CYCLES. Latest review:\n$(extract_review_notes "$PROGRAMMER_REVIEW_OUT")"
      log "$feedback"
      save_state
    fi

    CURRENT_PHASE="$PHASE_TESTER"
    save_state
  fi

  if [[ "$CURRENT_PHASE" == "$PHASE_TESTER" ]]; then
    if [[ -z "${PROGRAMMER_OUT//[[:space:]]/}" ]]; then
      log "[round $round] missing PROGRAMMER_OUT while resuming tester phase; falling back to programmer phase"
      CURRENT_PHASE="$PHASE_PROGRAMMER"
      save_state
      continue
    fi

    log "[round $round] tester: running scenario test"
    TESTER_MSG="$(printf '%s\n' \
      "*** SCENARIO TEST ***" \
      "$SCENARIO_TEST" \
      "" \
      "Programmer output:" \
      "$PROGRAMMER_OUT" \
      "" \
      "Guard lines:" \
      "tester: dont implement code, dont modify openspec artifact" \
      "" \
      "Task:" \
      "1) Run tests based on SCENARIO TEST only." \
      "2) Return strict machine-readable result:" \
      "RESULT: PASS or RESULT: FAIL" \
      "EVIDENCE:" \
      "- Commands run:" \
      "- Key outputs:" \
      "- Failed criteria (if any):" \
      "- Recommended next fix:")"
    TESTER_BEFORE="$(get_structured_output "$TESTER_ID" "$TEST_RESULT_REGEX" 2>/dev/null || true)"
    send_input "$TESTER_ID" "$TESTER_MSG"
    wait_for_expected_output "$TESTER_ID" "$TESTER_BEFORE" "$TEST_RESULT_REGEX" 1800
    TEST_OUT="$(get_structured_output "$TESTER_ID" "$TEST_RESULT_REGEX")"
    save_state

    echo "$TEST_OUT"

    if echo "$TEST_OUT" | grep -Eiq "$PASS_RESULT_REGEX"; then
      CURRENT_PHASE="$PHASE_DONE"
      FINAL_STATUS="PASS"
      save_state
      echo
      log "FINAL: PASS"
      exit 0
    fi

    feedback="$(extract_test_evidence "$TEST_OUT")"
    log "[round $round] tester: FAIL, retrying with feedback"
    log "FINAL: FAIL (retrying)"

    CURRENT_ROUND=$((CURRENT_ROUND + 1))
    CURRENT_PHASE="$PHASE_ANALYST"
    analyst_feedback="None yet."
    programmer_feedback="None yet."
    ANALYST_OUT=""
    ANALYST_REVIEW_OUT=""
    PROGRAMMER_OUT=""
    PROGRAMMER_REVIEW_OUT=""
    TEST_OUT=""
    save_state
  fi
done

CURRENT_PHASE="$PHASE_DONE"
FINAL_STATUS="FAIL"
save_state
log "Reached MAX_ROUNDS=$MAX_ROUNDS without PASS"
exit 1
