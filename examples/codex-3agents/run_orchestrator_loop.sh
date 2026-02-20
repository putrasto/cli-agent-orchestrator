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

if [[ -n "$PROMPT_FILE" ]]; then
  if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "PROMPT_FILE not found: $PROMPT_FILE" >&2
    exit 1
  fi
  PROMPT="$(cat "$PROMPT_FILE")"
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
  local full_output line_no

  full_output="$(
    curl -fsS "$API/terminals/$terminal_id/output?mode=full" | jq -r '.output' \
      | sed -E $'s/\x1B\\[[0-9;?]*[ -/]*[@-~]//g' \
      | tr -d '\r'
  )"

  line_no="$(printf '%s\n' "$full_output" | grep -En "$marker_regex" | tail -n 1 | cut -d: -f1 || true)"
  if [[ -z "$line_no" ]]; then
    get_last_output "$terminal_id"
    return
  fi

  printf '%s\n' "$full_output" | tail -n +"$line_no" | awk '
    NR == 1 { print; next }
    /^[[:space:]]*›[[:space:]]/ { exit }
    /^[[:space:]]*\?[[:space:]]+for shortcuts/ { exit }
    /^[[:space:]]*[0-9]+%[[:space:]]+context left[[:space:]]*$/ { exit }
    { print }
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
  if echo "$review_text" | grep -Eiq "$APPROVED_REVIEW_REGEX"; then
    return 0
  fi
  return 1
}

ANALYST_JSON="$(create_session system_analyst)"
ANALYST_ID="$(echo "$ANALYST_JSON" | jq -r '.id')"
SESSION_NAME="$(echo "$ANALYST_JSON" | jq -r '.session_name')"

PEER_ANALYST_JSON="$(create_terminal "$SESSION_NAME" peer_system_analyst)"
PEER_ANALYST_ID="$(echo "$PEER_ANALYST_JSON" | jq -r '.id')"

PROGRAMMER_JSON="$(create_terminal "$SESSION_NAME" programmer)"
PROGRAMMER_ID="$(echo "$PROGRAMMER_JSON" | jq -r '.id')"

PEER_PROGRAMMER_JSON="$(create_terminal "$SESSION_NAME" peer_programmer)"
PEER_PROGRAMMER_ID="$(echo "$PEER_PROGRAMMER_JSON" | jq -r '.id')"

TESTER_JSON="$(create_terminal "$SESSION_NAME" tester)"
TESTER_ID="$(echo "$TESTER_JSON" | jq -r '.id')"

log "SESSION_NAME=$SESSION_NAME"
log "ANALYST_ID=$ANALYST_ID"
log "PEER_ANALYST_ID=$PEER_ANALYST_ID"
log "PROGRAMMER_ID=$PROGRAMMER_ID"
log "PEER_PROGRAMMER_ID=$PEER_PROGRAMMER_ID"
log "TESTER_ID=$TESTER_ID"

cleanup() {
  curl -fsS -X POST "$API/terminals/$ANALYST_ID/exit" >/dev/null || true
  curl -fsS -X POST "$API/terminals/$PEER_ANALYST_ID/exit" >/dev/null || true
  curl -fsS -X POST "$API/terminals/$PROGRAMMER_ID/exit" >/dev/null || true
  curl -fsS -X POST "$API/terminals/$PEER_PROGRAMMER_ID/exit" >/dev/null || true
  curl -fsS -X POST "$API/terminals/$TESTER_ID/exit" >/dev/null || true
}
trap cleanup EXIT

feedback="None yet."

for round in $(seq 1 "$MAX_ROUNDS"); do
  echo
  log "=== ROUND $round ==="

  analyst_feedback="None yet."
  ANALYST_APPROVED=0
  ANALYST_OUT=""
  ANALYST_REVIEW_OUT=""
  for analyst_cycle in $(seq 1 "$MAX_REVIEW_CYCLES"); do
    log "[round $round] system_analyst: cycle $analyst_cycle - exploring and updating openspec"
    ANALYST_MSG="$(printf '%s\n' \
      "*** ORIGINAL EXPLORE SUMMARY ***" \
      "$EXPLORE_SUMMARY" \
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
      "2) Create/update all OpenSpec artifacts using ff command." \
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

    log "[round $round] peer_system_analyst: cycle $analyst_cycle - reviewing analyst output"
    ANALYST_REVIEW_MSG="$(printf '%s\n' \
      "*** ORIGINAL EXPLORE SUMMARY ***" \
      "$EXPLORE_SUMMARY" \
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

    if is_review_approved "$ANALYST_REVIEW_OUT"; then
      log "[round $round] peer_system_analyst: APPROVED"
      ANALYST_APPROVED=1
      break
    fi
    log "[round $round] peer_system_analyst: REVISE"
    analyst_feedback="$ANALYST_REVIEW_OUT"
  done

  if [[ "$ANALYST_APPROVED" -ne 1 ]]; then
    log "[round $round] analyst gate: MAX_REVIEW_CYCLES reached, proceeding without approval"
    feedback="Peer analyst did not approve after MAX_REVIEW_CYCLES. Latest review:\n$ANALYST_REVIEW_OUT"
    log "$feedback"
  fi

  programmer_feedback="None yet."
  PROGRAMMER_APPROVED=0
  PROGRAMMER_OUT=""
  PROGRAMMER_REVIEW_OUT=""
  for programmer_cycle in $(seq 1 "$MAX_REVIEW_CYCLES"); do
    log "[round $round] programmer: cycle $programmer_cycle - applying openspec and implementing"
    PROGRAMMER_MSG="$(printf '%s\n' \
      "*** ORIGINAL EXPLORE SUMMARY ***" \
      "$EXPLORE_SUMMARY" \
      "" \
      "System analyst output:" \
      "$ANALYST_OUT" \
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

    log "[round $round] peer_programmer: cycle $programmer_cycle - reviewing implementation"
    PROGRAMMER_REVIEW_MSG="$(printf '%s\n' \
      "*** ORIGINAL EXPLORE SUMMARY ***" \
      "$EXPLORE_SUMMARY" \
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

    if is_review_approved "$PROGRAMMER_REVIEW_OUT"; then
      log "[round $round] peer_programmer: APPROVED"
      PROGRAMMER_APPROVED=1
      break
    fi
    log "[round $round] peer_programmer: REVISE"
    programmer_feedback="$PROGRAMMER_REVIEW_OUT"
  done

  if [[ "$PROGRAMMER_APPROVED" -ne 1 ]]; then
    log "[round $round] programmer gate: MAX_REVIEW_CYCLES reached, proceeding without approval"
    feedback="Peer programmer did not approve after MAX_REVIEW_CYCLES. Latest review:\n$PROGRAMMER_REVIEW_OUT"
    log "$feedback"
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

  echo "$TEST_OUT"

  if echo "$TEST_OUT" | grep -Eiq "$PASS_RESULT_REGEX"; then
    echo
    log "FINAL: PASS"
    exit 0
  fi

  feedback="$TEST_OUT"
  log "[round $round] tester: FAIL, retrying with feedback"
  log "FINAL: FAIL (retrying)"
done

log "Reached MAX_ROUNDS=$MAX_ROUNDS without PASS"
exit 1
