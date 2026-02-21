"""Unit tests for the Python orchestrator loop pure functions."""

import json
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import httpx
import pytest

# Add the examples directory so we can import the module
EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples" / "agnostic-3agents"
sys.path.insert(0, str(EXAMPLES_DIR))

import run_orchestrator_loop as orch


# ── _extract_prompt_section ─────────────────────────────────────────────────


class TestExtractPromptSection:
    def test_between_two_headers(self):
        text = (
            "preamble\n"
            "*** ORIGINAL EXPLORE SUMMARY ***\n"
            "explore line 1\n"
            "explore line 2\n"
            "*** SCENARIO TEST ***\n"
            "test line 1"
        )
        result = orch._extract_prompt_section(
            text, "*** ORIGINAL EXPLORE SUMMARY ***", "*** SCENARIO TEST ***"
        )
        assert result == "explore line 1\nexplore line 2"

    def test_from_header_to_end(self):
        text = (
            "preamble\n"
            "*** SCENARIO TEST ***\n"
            "test line 1\n"
            "test line 2"
        )
        result = orch._extract_prompt_section(text, "*** SCENARIO TEST ***")
        assert result == "test line 1\ntest line 2"

    def test_missing_header_returns_empty(self):
        result = orch._extract_prompt_section("no headers here", "*** MISSING ***")
        assert result == ""

    def test_empty_section_between_adjacent_headers(self):
        text = (
            "*** ORIGINAL EXPLORE SUMMARY ***\n"
            "*** SCENARIO TEST ***\n"
            "test data"
        )
        result = orch._extract_prompt_section(
            text, "*** ORIGINAL EXPLORE SUMMARY ***", "*** SCENARIO TEST ***"
        )
        assert result == ""


# ── _extract_section (regex-based, for review notes) ────────────────────────


class TestExtractSection:
    def test_extracts_from_matching_line(self):
        text = (
            "Some preamble\n"
            "REVIEW_NOTES: here are notes\n"
            "  - point 1\n"
            "  - point 2"
        )
        result = orch._extract_section(text, r"^\s*REVIEW_NOTES:")
        assert "REVIEW_NOTES: here are notes" in result
        assert "- point 1" in result
        assert "- point 2" in result

    def test_no_match_returns_empty(self):
        result = orch._extract_section("no notes here", r"^\s*REVIEW_NOTES:")
        assert result == ""

    def test_indented_match(self):
        text = "  REVIEW_NOTES: indented\ndetails"
        result = orch._extract_section(text, r"^\s*REVIEW_NOTES:")
        assert "REVIEW_NOTES: indented" in result

    def test_bounded_by_stop_pattern(self):
        text = (
            "- Scope: big scope\n"
            "- Implementation notes: do X\n"
            "  with Y\n"
            "- Risks: low risk\n"
            "- Downstream: affects Z"
        )
        result = orch._extract_section(
            text, r"^\s*-?\s*Implementation notes", r"^\s*-?\s*Risks"
        )
        assert "Implementation notes: do X" in result
        assert "with Y" in result
        # Should NOT include Risks or anything after it
        assert "Risks" not in result
        assert "Downstream" not in result

    def test_stop_pattern_not_found_goes_to_end(self):
        text = "- Implementation notes: do X\n  detail line"
        result = orch._extract_section(
            text, r"^\s*-?\s*Implementation notes", r"^\s*-?\s*NONEXISTENT"
        )
        assert "Implementation notes: do X" in result
        assert "detail line" in result


# ── is_review_approved ──────────────────────────────────────────────────────


class TestIsReviewApproved:
    """Tests with default config: MIN_REVIEW_CYCLES_BEFORE_APPROVAL=2,
    REQUIRE_REVIEW_EVIDENCE=True, REVIEW_EVIDENCE_MIN_MATCH=3."""

    def test_approved_with_sufficient_analyst_evidence(self):
        review = textwrap.dedent("""\
            REVIEW_RESULT: APPROVED
            REVIEW_NOTES:
            - proposal verified as complete with correct tasks.
            - P1 traceability confirmed across all phases.
            - downstream contract references api_service.py module.
            - handoff includes 3 concrete action items for programmer.
        """)
        assert orch.is_review_approved(review, 2, "analyst") is True

    def test_approved_with_sufficient_programmer_evidence(self):
        review = textwrap.dedent("""\
            REVIEW_RESULT: APPROVED
            REVIEW_NOTES:
            - Implementation code changes in 3 files look correct.
            - Validation test command runs clean, pytest passes.
            - Risk of regression is low, quality coverage is adequate.
            - No remaining issues or defects found.
        """)
        assert orch.is_review_approved(review, 2, "programmer") is True

    def test_rejected_when_no_approved_keyword(self):
        review = "REVIEW_RESULT: REVISE\nREVIEW_NOTES: needs work"
        assert orch.is_review_approved(review, 2, "analyst") is False

    def test_rejected_on_cycle_1(self):
        review = textwrap.dedent("""\
            REVIEW_RESULT: APPROVED
            REVIEW_NOTES:
            - proposal verified as complete.
            - P1 traceability confirmed across phases.
            - downstream contract references api_service.py module.
            - handoff includes 3 concrete action items.
        """)
        assert orch.is_review_approved(review, 1, "analyst") is False

    def test_rejected_when_no_review_notes(self):
        review = "REVIEW_RESULT: APPROVED\nLooks good!"
        assert orch.is_review_approved(review, 2, "analyst") is False

    def test_rejected_when_insufficient_evidence(self):
        review = textwrap.dedent("""\
            REVIEW_RESULT: APPROVED
            REVIEW_NOTES:
            - proposal verified as complete.
        """)
        # Only 1 evidence pattern match, need 3
        assert orch.is_review_approved(review, 2, "analyst") is False

    def test_rejected_trivial_review_with_domain_words_only(self):
        """Domain keywords without assessment co-occurrence should fail."""
        review = textwrap.dedent("""\
            REVIEW_RESULT: APPROVED
            REVIEW_NOTES:
            - Looks good, artifacts and downstream handoff are fine.
            - P1 and traceability covered. Scope is clear.
        """)
        assert orch.is_review_approved(review, 2, "analyst") is False

    def test_approved_without_evidence_when_disabled(self):
        original = orch.REQUIRE_REVIEW_EVIDENCE
        try:
            orch.REQUIRE_REVIEW_EVIDENCE = False
            review = "REVIEW_RESULT: APPROVED\nAll good."
            assert orch.is_review_approved(review, 2, "analyst") is True
        finally:
            orch.REQUIRE_REVIEW_EVIDENCE = original


# ── extract_review_notes ────────────────────────────────────────────────────


class TestExtractReviewNotes:
    def test_condenses_to_review_notes_section(self):
        review = (
            "Preamble discussion\n"
            "REVIEW_NOTES: key findings\n"
            "  - point A\n"
            "  - point B"
        )
        result = orch.extract_review_notes(review)
        assert result.startswith("REVIEW_NOTES:")
        assert "point A" in result
        assert "Preamble" not in result

    def test_falls_back_to_full_text_when_no_notes_section(self):
        review = "Just some review text without the marker."
        result = orch.extract_review_notes(review)
        assert "Just some review text" in result

    def test_respects_max_feedback_lines(self):
        lines = ["REVIEW_NOTES:"] + [f"line {i}" for i in range(100)]
        review = "\n".join(lines)
        result = orch.extract_review_notes(review)
        assert len(result.splitlines()) <= orch.MAX_FEEDBACK_LINES

    def test_passthrough_when_condensation_disabled(self):
        original = orch.CONDENSE_REVIEW_FEEDBACK
        try:
            orch.CONDENSE_REVIEW_FEEDBACK = False
            review = "Full review text\nREVIEW_NOTES: notes"
            result = orch.extract_review_notes(review)
            assert result == review
        finally:
            orch.CONDENSE_REVIEW_FEEDBACK = original


# ── extract_test_evidence ───────────────────────────────────────────────────


class TestExtractTestEvidence:
    def test_extracts_result_and_evidence(self):
        text = textwrap.dedent("""\
            Discussion here
            RESULT: FAIL
            More text
            EVIDENCE:
            - Commands run: pytest
            - Key outputs: 3 failed
        """)
        result = orch.extract_test_evidence(text)
        assert "RESULT: FAIL" in result
        assert "EVIDENCE:" in result
        assert "Commands run" in result
        assert "Discussion here" not in result

    def test_falls_back_when_no_markers(self):
        text = "Just plain test output with no markers."
        result = orch.extract_test_evidence(text)
        assert "Just plain test output" in result


# ── explore_block_for ───────────────────────────────────────────────────────


class TestExploreBlockFor:
    def setup_method(self):
        orch._explore_sent.clear()
        # Set module-level EXPLORE_SUMMARY for test
        orch.EXPLORE_SUMMARY = "Detailed explore content here."

    def test_first_call_returns_full_summary(self):
        result = orch.explore_block_for("term-001")
        assert "*** ORIGINAL EXPLORE SUMMARY ***" in result
        assert "Detailed explore content here." in result

    def test_second_call_returns_condensed(self):
        orch.explore_block_for("term-001")
        result = orch.explore_block_for("term-001")
        assert "refer to your conversation history" in result
        assert "Detailed explore content" not in result

    def test_different_terminals_get_full(self):
        result1 = orch.explore_block_for("term-001")
        result2 = orch.explore_block_for("term-002")
        assert "Detailed explore content here." in result1
        assert "Detailed explore content here." in result2

    def test_passthrough_when_condensation_disabled(self):
        original = orch.CONDENSE_EXPLORE_ON_REPEAT
        try:
            orch.CONDENSE_EXPLORE_ON_REPEAT = False
            orch.explore_block_for("term-001")
            result = orch.explore_block_for("term-001")
            assert "Detailed explore content here." in result
        finally:
            orch.CONDENSE_EXPLORE_ON_REPEAT = original


# ── Prompt builders ─────────────────────────────────────────────────────────


class TestPromptBuilders:
    def setup_method(self):
        orch._explore_sent.clear()
        orch.EXPLORE_SUMMARY = "Explore summary text."
        orch.SCENARIO_TEST = "Run the test scenario."
        orch.terminal_ids.update({
            "analyst": "a001",
            "peer_analyst": "a002",
            "programmer": "p001",
            "peer_programmer": "p002",
            "tester": "t001",
        })
        orch.feedback = "None yet."
        orch.analyst_feedback = "None yet."
        orch.programmer_feedback = "None yet."

    def test_analyst_prompt_has_required_parts(self):
        prompt = orch.build_analyst_prompt(1, 1)
        assert "ORIGINAL EXPLORE SUMMARY" in prompt
        assert "Round: 1" in prompt
        assert "Analyst review cycle: 1" in prompt
        assert "ANALYST_SUMMARY" in prompt
        assert "RESPONSE FILE INSTRUCTION" in prompt
        assert "analyst_summary.md" in prompt

    def test_analyst_review_prompt_has_required_parts(self):
        prompt = orch.build_analyst_review_prompt("analyst output here")
        assert "analyst output here" in prompt
        assert "REVIEW_RESULT" in prompt
        assert "RESPONSE FILE INSTRUCTION" in prompt
        assert "analyst_review.md" in prompt
        # Hardened checklist
        assert "default stance is REVISE" in prompt
        assert "Rejection criteria" in prompt
        assert "Codebase verification" in prompt
        assert "Implementation notes" in prompt
        assert "Risks" in prompt
        assert "Downstream impact" in prompt

    def test_programmer_prompt_has_required_parts(self):
        analyst_out = (
            "ANALYST_SUMMARY:\n"
            "- OpenSpec artifacts created/updated: proposal.md\n"
            "- Implementation notes for programmer: do X and Y\n"
            "- Risks/assumptions: low risk"
        )
        prompt = orch.build_programmer_prompt(1, 1, analyst_out)
        assert "Implementation notes" in prompt
        assert "PROGRAMMER_SUMMARY" in prompt
        assert "RESPONSE FILE INSTRUCTION" in prompt
        assert "programmer_summary.md" in prompt

    def test_programmer_prompt_condenses_upstream_on_repeat(self):
        prompt = orch.build_programmer_prompt(1, 2, "the actual detailed analyst text")
        assert "refer to conversation history" in prompt
        assert "the actual detailed analyst text" not in prompt

    def test_programmer_prompt_condenses_cross_phase(self):
        """Programmer gets condensed analyst output, not the full summary."""
        analyst_out = (
            "ANALYST_SUMMARY:\n"
            "- Scope: very long scope section with lots of detail\n"
            "- OpenSpec artifacts created/updated: proposal.md, design.md\n"
            "- Implementation notes for programmer: implement feature X\n"
            "- Risks/assumptions: low risk"
        )
        prompt = orch.build_programmer_prompt(1, 1, analyst_out)
        # Cross-phase condensation extracts handoff sections
        assert "Implementation notes" in prompt
        # Full scope section should not appear (condensed away)
        assert "very long scope section with lots of detail" not in prompt

    def test_programmer_review_gets_full_output(self):
        """Peer review (pingpong) gets FULL programmer output, not condensed."""
        prompt = orch.build_programmer_review_prompt("programmer output here with all details")
        assert "programmer output here with all details" in prompt
        assert "REVIEW_RESULT" in prompt
        assert "RESPONSE FILE INSTRUCTION" in prompt
        assert "programmer_review.md" in prompt

    def test_tester_prompt_has_required_parts(self):
        programmer_out = (
            "PROGRAMMER_SUMMARY:\n"
            "- Files changed: src/main.py\n"
            "- Behavior implemented: added feature X"
        )
        prompt = orch.build_tester_prompt(programmer_out)
        assert "SCENARIO TEST" in prompt
        assert "Run the test scenario." in prompt
        assert "Files changed" in prompt
        assert "RESULT: PASS or RESULT: FAIL" in prompt
        assert "RESPONSE FILE INSTRUCTION" in prompt
        assert "test_result.md" in prompt

    def test_tester_prompt_condenses_cross_phase(self):
        """Tester gets condensed programmer output, not the full summary."""
        programmer_out = (
            "PROGRAMMER_SUMMARY:\n"
            "- openspec-apply-change result: success with verbose details here\n"
            "- Files changed: src/main.py, src/utils.py\n"
            "- Behavior implemented: added validation logic\n"
            "- Known limitations: none"
        )
        prompt = orch.build_tester_prompt(programmer_out)
        assert "Files changed" in prompt
        assert "Behavior implemented" in prompt
        # Full apply-change result should be condensed away
        assert "verbose details here" not in prompt


# ── Cross-phase condensation functions ─────────────────────────────────────


class TestCondenseAnalystForProgrammer:
    def test_extracts_impl_notes_and_risks_bounded(self):
        analyst_out = (
            "ANALYST_SUMMARY:\n"
            "- Scope: build the widget feature end to end\n"
            "- Implementation notes for programmer: use factory pattern\n"
            "  with dependency injection for testability\n"
            "- Risks/assumptions: assumes API v2 is available\n"
            "- Downstream impact: tester needs new fixtures"
        )
        result = orch.condense_analyst_for_programmer(analyst_out)
        assert "Implementation notes" in result
        assert "factory pattern" in result
        assert "Risks/assumptions" in result
        # Scope should NOT be included
        assert "build the widget feature end to end" not in result
        # Downstream impact should NOT be included (bounded extraction)
        assert "tester needs new fixtures" not in result

    def test_extracts_openspec_artifacts_bounded(self):
        analyst_out = (
            "- Scope: big scope\n"
            "- OpenSpec artifacts created/updated: proposal.md, design.md\n"
            "  spec changes: added new requirement\n"
            "- Implementation notes for programmer: do the thing\n"
            "- Risks/assumptions: none\n"
            "- Downstream impact: affects tester"
        )
        result = orch.condense_analyst_for_programmer(analyst_out)
        assert "OpenSpec artifacts" in result
        assert "proposal.md" in result
        assert "Implementation notes" in result
        # Scope and downstream should NOT be included
        assert "big scope" not in result
        assert "affects tester" not in result

    def test_falls_back_to_head_truncated_when_no_markers(self):
        # No known section markers
        analyst_out = "line1\nline2\nline3\nline4\nline5"
        result = orch.condense_analyst_for_programmer(analyst_out)
        assert result == analyst_out  # short enough, all lines returned

    def test_passthrough_when_condensation_disabled(self):
        original = orch.CONDENSE_CROSS_PHASE
        try:
            orch.CONDENSE_CROSS_PHASE = False
            analyst_out = "full analyst output with all details"
            result = orch.condense_analyst_for_programmer(analyst_out)
            assert result == analyst_out
        finally:
            orch.CONDENSE_CROSS_PHASE = original

    def test_respects_max_cross_phase_lines(self):
        original = orch.MAX_CROSS_PHASE_LINES
        try:
            orch.MAX_CROSS_PHASE_LINES = 3
            analyst_out = (
                "- Implementation notes for programmer: line1\n"
                "  line2\n"
                "  line3\n"
                "  line4\n"
                "  line5"
            )
            result = orch.condense_analyst_for_programmer(analyst_out)
            assert len(result.splitlines()) == 3
        finally:
            orch.MAX_CROSS_PHASE_LINES = original


class TestCondenseProgrammerForTester:
    def test_extracts_files_and_behavior_bounded(self):
        programmer_out = (
            "PROGRAMMER_SUMMARY:\n"
            "- apply result: ran successfully\n"
            "- Files changed: src/main.py, src/utils.py\n"
            "  also touched src/config.py\n"
            "- Behavior implemented: added input validation\n"
            "  and error handling for edge cases\n"
            "- Known limitations: none"
        )
        result = orch.condense_programmer_for_tester(programmer_out)
        assert "Files changed" in result
        assert "src/main.py" in result
        assert "Behavior implemented" in result
        assert "input validation" in result
        # apply result detail should NOT be included
        assert "ran successfully" not in result
        # Known limitations should NOT be included (bounded extraction)
        assert "Known limitations" not in result

    def test_falls_back_to_head_truncated_when_no_markers(self):
        programmer_out = "just some unstructured output\nwith multiple lines"
        result = orch.condense_programmer_for_tester(programmer_out)
        assert result == programmer_out

    def test_passthrough_when_condensation_disabled(self):
        original = orch.CONDENSE_CROSS_PHASE
        try:
            orch.CONDENSE_CROSS_PHASE = False
            programmer_out = "full programmer output with all details"
            result = orch.condense_programmer_for_tester(programmer_out)
            assert result == programmer_out
        finally:
            orch.CONDENSE_CROSS_PHASE = original

    def test_respects_max_cross_phase_lines(self):
        original = orch.MAX_CROSS_PHASE_LINES
        try:
            orch.MAX_CROSS_PHASE_LINES = 2
            programmer_out = (
                "- Files changed: a.py\n"
                "  b.py\n"
                "  c.py\n"
                "  d.py"
            )
            result = orch.condense_programmer_for_tester(programmer_out)
            assert len(result.splitlines()) == 2
        finally:
            orch.MAX_CROSS_PHASE_LINES = original


# ── response_file_instruction ───────────────────────────────────────────────


class TestResponseFileInstruction:
    def test_contains_absolute_path(self):
        result = orch.response_file_instruction("analyst")
        assert "RESPONSE FILE INSTRUCTION" in result
        assert "analyst_summary.md" in result
        # Should be an absolute path
        assert str(orch.RESPONSE_DIR) in result

    def test_all_roles_have_instructions(self):
        for role in orch.RESPONSE_FILES:
            result = orch.response_file_instruction(role)
            assert orch.RESPONSE_FILES[role] in result


# ── State management ────────────────────────────────────────────────────────


class TestStateManagement:
    def test_save_and_load_roundtrip(self, tmp_path):
        state_file = str(tmp_path / "state.json")
        original_state_file = orch.STATE_FILE

        try:
            orch.STATE_FILE = state_file
            orch.session_name = "cao-test1234"
            orch.terminal_ids.update({
                "analyst": "aa11",
                "peer_analyst": "bb22",
                "programmer": "cc33",
                "peer_programmer": "dd44",
                "tester": "ee55",
            })
            orch.current_round = 3
            orch.current_phase = orch.PHASE_PROGRAMMER
            orch.final_status = "RUNNING"
            orch.feedback = "Some test feedback."
            orch.analyst_feedback = "Analyst notes."
            orch.programmer_feedback = "Programmer notes."
            orch.outputs.update({
                "analyst": "analyst output",
                "analyst_review": "review output",
                "programmer": "",
                "programmer_review": "",
                "tester": "",
            })

            orch.save_state()

            # Reset globals
            orch.session_name = ""
            orch.current_round = 1
            orch.current_phase = orch.PHASE_ANALYST
            for k in orch.terminal_ids:
                orch.terminal_ids[k] = ""
            for k in orch.outputs:
                orch.outputs[k] = ""

            assert orch.load_state() is True
            assert orch.session_name == "cao-test1234"
            assert orch.terminal_ids["analyst"] == "aa11"
            assert orch.terminal_ids["tester"] == "ee55"
            assert orch.current_round == 3
            assert orch.current_phase == orch.PHASE_PROGRAMMER
            assert orch.feedback == "Some test feedback."
            assert orch.outputs["analyst"] == "analyst output"
        finally:
            orch.STATE_FILE = original_state_file

    def test_load_state_missing_file(self, tmp_path):
        original_state_file = orch.STATE_FILE
        try:
            orch.STATE_FILE = str(tmp_path / "nonexistent.json")
            assert orch.load_state() is False
        finally:
            orch.STATE_FILE = original_state_file

    def test_state_json_format_with_per_agent_provider(self, tmp_path):
        """Verify the JSON structure includes per-agent provider info."""
        state_file = str(tmp_path / "state.json")
        original_state_file = orch.STATE_FILE
        try:
            orch.STATE_FILE = state_file
            orch.session_name = "cao-abcdef12"
            orch.terminal_ids.update({
                "analyst": "11111111",
                "peer_analyst": "22222222",
                "programmer": "33333333",
                "peer_programmer": "44444444",
                "tester": "55555555",
            })
            orch.current_round = 1
            orch.current_phase = orch.PHASE_ANALYST
            orch.final_status = "RUNNING"
            orch.save_state()

            data = json.loads(Path(state_file).read_text())
            assert data["version"] == 1
            assert "updated_at" in data
            assert data["session_name"] == "cao-abcdef12"
            # Terminals now stored as {"id": ..., "provider": ...}
            assert data["terminals"]["analyst"]["id"] == "11111111"
            assert data["terminals"]["analyst"]["provider"] == orch.AGENT_CONFIG["analyst"]["provider"]
            assert data["terminals"]["peer_analyst"]["id"] == "22222222"
            assert data["terminals"]["programmer"]["id"] == "33333333"
            assert data["terminals"]["peer_programmer"]["id"] == "44444444"
            assert data["terminals"]["tester"]["id"] == "55555555"
            assert data["current_round"] == 1
            assert data["current_phase"] == "analyst"
            assert data["final_status"] == "RUNNING"
            assert "outputs" in data
            assert "feedback" in data
        finally:
            orch.STATE_FILE = original_state_file

    def test_load_invalid_round_defaults_to_1(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "current_round": "invalid",
            "current_phase": "analyst",
            "terminals": {},
            "outputs": {},
        }))
        original_state_file = orch.STATE_FILE
        try:
            orch.STATE_FILE = str(state_file)
            orch.load_state()
            assert orch.current_round == 1
        finally:
            orch.STATE_FILE = original_state_file

    def test_load_invalid_phase_defaults_to_analyst(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "current_round": 1,
            "current_phase": "invalid_phase",
            "terminals": {},
            "outputs": {},
        }))
        original_state_file = orch.STATE_FILE
        try:
            orch.STATE_FILE = str(state_file)
            orch.load_state()
            assert orch.current_phase == orch.PHASE_ANALYST
        finally:
            orch.STATE_FILE = original_state_file


# ── File handoff helpers ────────────────────────────────────────────────────


class TestFileHandoff:
    def test_response_path_for_all_roles(self):
        for role, filename in orch.RESPONSE_FILES.items():
            p = orch.response_path_for(role)
            assert p.name == filename
            assert p.parent == orch.RESPONSE_DIR

    def test_clear_stale_response(self, tmp_path):
        original_dir = orch.RESPONSE_DIR
        original_wd = orch.WD
        original_ts = orch._run_timestamp
        original_seq = orch._response_seq
        try:
            orch.RESPONSE_DIR = tmp_path
            orch.WD = str(tmp_path)
            orch._run_timestamp = "2026-01-01T00-00-00"
            orch._response_seq = 0
            f = tmp_path / "analyst_summary.md"
            f.write_text("stale data")
            orch.RESPONSE_FILES["analyst"] = "analyst_summary.md"
            orch.clear_stale_response("analyst")
            assert not f.exists()
            # Should be archived, not deleted
            archived = tmp_path / ".tmp" / "2026-01-01T00-00-00" / "001-analyst-stale.md"
            assert archived.exists()
            assert archived.read_text() == "stale data"
        finally:
            orch.RESPONSE_DIR = original_dir
            orch.WD = original_wd
            orch._run_timestamp = original_ts
            orch._response_seq = original_seq

    def test_clear_stale_response_no_file(self, tmp_path):
        original_dir = orch.RESPONSE_DIR
        try:
            orch.RESPONSE_DIR = tmp_path
            # Should not raise
            orch.clear_stale_response("analyst")
        finally:
            orch.RESPONSE_DIR = original_dir

    def test_ensure_response_dir(self, tmp_path):
        original_dir = orch.RESPONSE_DIR
        original_ts = orch._run_timestamp
        try:
            new_dir = tmp_path / "nested" / "agent-responses"
            orch.RESPONSE_DIR = new_dir
            orch._run_timestamp = ""
            orch.ensure_response_dir()
            assert new_dir.is_dir()
            assert orch._run_timestamp  # should be set after ensure_response_dir
        finally:
            orch.RESPONSE_DIR = original_dir
            orch._run_timestamp = original_ts


# ── test_command_instruction ────────────────────────────────────────────────


class TestTestCommandInstruction:
    def test_with_explicit_command(self):
        original = orch.PROJECT_TEST_CMD
        try:
            orch.PROJECT_TEST_CMD = "conda run -n myenv pytest -x"
            result = orch._test_command_instruction()
            assert "conda run -n myenv pytest -x" in result
        finally:
            orch.PROJECT_TEST_CMD = original

    def test_without_explicit_command(self):
        original = orch.PROJECT_TEST_CMD
        try:
            orch.PROJECT_TEST_CMD = ""
            result = orch._test_command_instruction()
            assert "AGENTS.md" in result
        finally:
            orch.PROJECT_TEST_CMD = original


# ── wait_for_response_file ──────────────────────────────────────────────────


class TestWaitForResponseFile:
    """Tests for poll loop, status gate, fallback, and strict mode."""

    def setup_method(self):
        self._orig_dir = orch.RESPONSE_DIR
        self._orig_strict = orch.STRICT_FILE_HANDOFF
        self._orig_poll = orch.POLL_SECONDS
        self._orig_grace = orch.IDLE_GRACE_SECONDS
        self._orig_wd = orch.WD
        self._orig_ts = orch._run_timestamp
        self._orig_seq = orch._response_seq

    def teardown_method(self):
        orch.RESPONSE_DIR = self._orig_dir
        orch.STRICT_FILE_HANDOFF = self._orig_strict
        orch.POLL_SECONDS = self._orig_poll
        orch.IDLE_GRACE_SECONDS = self._orig_grace
        orch.WD = self._orig_wd
        orch._run_timestamp = self._orig_ts
        orch._response_seq = self._orig_seq

    @patch.object(orch.api, "get_status")
    def test_file_exists_and_idle_returns_content(self, mock_status, tmp_path):
        orch.RESPONSE_DIR = tmp_path
        orch.WD = str(tmp_path)
        orch._run_timestamp = "2026-01-01T00-00-00"
        orch._response_seq = 0
        resp_file = tmp_path / "analyst_summary.md"
        resp_file.write_text("ANALYST_SUMMARY:\nGood analysis.")
        mock_status.return_value = "idle"

        result = orch.wait_for_response_file("analyst", "term-001", timeout=5)
        assert "ANALYST_SUMMARY" in result
        assert "Good analysis." in result
        assert not resp_file.exists()  # moved, not at original location
        # Verify archived
        archived = tmp_path / ".tmp" / "2026-01-01T00-00-00" / "001-analyst.md"
        assert archived.exists()

    @patch.object(orch.api, "get_status")
    def test_waits_for_idle_before_reading(self, mock_status, tmp_path):
        """File exists but terminal still processing — should wait."""
        orch.RESPONSE_DIR = tmp_path
        orch.WD = str(tmp_path)
        orch._run_timestamp = "test-run"
        orch._response_seq = 0
        orch.POLL_SECONDS = 0  # no sleep in test
        resp_file = tmp_path / "analyst_summary.md"
        resp_file.write_text("ANALYST_SUMMARY:\nContent here.")

        # First call: processing, second call: idle
        mock_status.side_effect = ["processing", "idle"]

        result = orch.wait_for_response_file("analyst", "term-001", timeout=10)
        assert "Content here." in result
        assert mock_status.call_count == 2

    @patch.object(orch.api, "get_status")
    def test_error_status_raises(self, mock_status, tmp_path):
        orch.RESPONSE_DIR = tmp_path
        mock_status.return_value = "error"

        with pytest.raises(RuntimeError, match="ERROR state"):
            orch.wait_for_response_file("analyst", "term-001", timeout=5)

    @patch.object(orch.api, "get_last_output", return_value="fallback output")
    @patch.object(orch.api, "get_status", return_value="completed")
    @patch("run_orchestrator_loop.time")
    def test_fallback_on_idle_grace_expired(self, mock_time, mock_status, mock_last, tmp_path):
        """No file written but terminal completed — idle grace triggers fallback."""
        orch.RESPONSE_DIR = tmp_path
        orch.STRICT_FILE_HANDOFF = False
        orch.IDLE_GRACE_SECONDS = 10
        # start=0 | poll1: idle_since=1, elapsed=2 (ok) | poll2: idle_check=15 (>grace) → fallback
        mock_time.monotonic.side_effect = [0.0, 1.0, 2.0, 15.0]
        mock_time.sleep = MagicMock()

        result = orch.wait_for_response_file("analyst", "term-001", timeout=1800)
        assert result == "fallback output"
        mock_last.assert_called_once_with("term-001")

    @patch.object(orch.api, "get_status", return_value="completed")
    @patch("run_orchestrator_loop.time")
    def test_strict_mode_raises_on_idle_grace_expired(self, mock_time, mock_status, tmp_path):
        """STRICT_FILE_HANDOFF=1: idle grace expired, raises RuntimeError."""
        orch.RESPONSE_DIR = tmp_path
        orch.STRICT_FILE_HANDOFF = True
        orch.IDLE_GRACE_SECONDS = 10
        # start=0 | poll1: idle_since=1, elapsed=2 (ok) | poll2: idle_check=15 (>grace) → error
        mock_time.monotonic.side_effect = [0.0, 1.0, 2.0, 15.0]
        mock_time.sleep = MagicMock()

        with pytest.raises(RuntimeError, match="did not write response file"):
            orch.wait_for_response_file("analyst", "term-001", timeout=1800)

    @patch.object(orch.api, "get_status", return_value="processing")
    @patch("run_orchestrator_loop.time")
    def test_timeout_while_processing_raises(self, mock_time, mock_status, tmp_path):
        """Timeout with terminal still processing — raises TimeoutError."""
        orch.RESPONSE_DIR = tmp_path
        mock_time.monotonic.side_effect = [0.0, 9999.0]
        mock_time.sleep = MagicMock()

        with pytest.raises(TimeoutError, match="Timeout"):
            orch.wait_for_response_file("analyst", "term-001", timeout=1)

    @patch.object(orch.api, "get_status")
    def test_empty_file_falls_through(self, mock_status, tmp_path):
        """Empty response file should not be accepted — falls through to next poll."""
        orch.RESPONSE_DIR = tmp_path
        orch.POLL_SECONDS = 0
        resp_file = tmp_path / "analyst_summary.md"
        resp_file.write_text("")  # empty

        call_count = [0]
        def status_side_effect(tid):
            call_count[0] += 1
            if call_count[0] == 1:
                return "idle"  # first: empty file + idle
            # Write real content for second poll
            resp_file.write_text("ANALYST_SUMMARY:\nReal content.")
            return "idle"
        mock_status.side_effect = status_side_effect

        result = orch.wait_for_response_file("analyst", "term-001", timeout=10)
        assert "Real content." in result


# ── send_and_wait ───────────────────────────────────────────────────────────


class TestSendAndWait:
    @patch("run_orchestrator_loop.wait_for_response_file", return_value="response content")
    @patch("run_orchestrator_loop.clear_stale_response")
    @patch.object(orch.api, "send_input")
    def test_clears_sends_waits(self, mock_send, mock_clear, mock_wait):
        result = orch.send_and_wait("term-001", "analyst", "do analysis")

        mock_clear.assert_called_once_with("analyst")
        mock_send.assert_called_once_with("term-001", "do analysis")
        mock_wait.assert_called_once_with("analyst", "term-001")
        assert result == "response content"


# ── response_file_instruction heredoc fix ───────────────────────────────────


class TestHeredocInstruction:
    def test_heredoc_contains_actual_path_not_placeholder(self):
        """CRITICAL fix: heredoc must show actual file path, not <path>."""
        import shlex
        result = orch.response_file_instruction("analyst")
        actual_path = str(orch.response_path_for("analyst"))
        quoted_path = shlex.quote(actual_path)
        # The cat command line must contain the shell-quoted absolute path
        assert f"cat << 'AGENT_EOF' > {quoted_path}" in result
        # Must NOT contain the literal "<path>" placeholder
        assert "< <path>" not in result
        assert "> <path>" not in result

    def test_heredoc_valid_for_all_roles(self):
        import shlex
        for role in orch.RESPONSE_FILES:
            result = orch.response_file_instruction(role)
            path = shlex.quote(str(orch.response_path_for(role)))
            assert f"> {path}" in result

    def test_heredoc_path_is_shell_safe_with_spaces(self):
        """Paths with spaces must be properly quoted."""
        import shlex
        original_dir = orch.RESPONSE_DIR
        try:
            orch.RESPONSE_DIR = Path("/tmp/my project/agent responses")
            result = orch.response_file_instruction("analyst")
            # shlex.quote wraps in single quotes for paths with spaces
            expected_path = shlex.quote("/tmp/my project/agent responses/analyst_summary.md")
            assert f"> {expected_path}" in result
            # The unquoted path with spaces must NOT appear in the cat command
            assert "cat << 'AGENT_EOF' > /tmp/my project" not in result
        finally:
            orch.RESPONSE_DIR = original_dir


# ── Auto-resume (should_auto_resume) ────────────────────────────────────────


class TestShouldAutoResume:
    """Tests that exercise the should_auto_resume() function directly."""

    def test_returns_true_when_state_running(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "final_status": "RUNNING",
            "current_round": 2,
            "current_phase": "programmer",
            "session_name": "cao-test",
            "terminals": {
                "analyst": "a1", "peer_analyst": "a2",
                "programmer": "p1", "peer_programmer": "p2",
                "tester": "t1",
            },
            "outputs": {},
        }))
        assert orch.should_auto_resume(str(state_file)) is True

    def test_returns_false_when_state_pass(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "final_status": "PASS",
            "current_round": 1,
            "current_phase": "done",
            "terminals": {},
            "outputs": {},
        }))
        assert orch.should_auto_resume(str(state_file)) is False

    def test_returns_false_when_state_fail(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "final_status": "FAIL",
            "current_round": 8,
            "current_phase": "done",
            "terminals": {},
            "outputs": {},
        }))
        assert orch.should_auto_resume(str(state_file)) is False

    def test_returns_false_when_no_file(self, tmp_path):
        assert orch.should_auto_resume(str(tmp_path / "nonexistent.json")) is False

    def test_returns_false_on_corrupt_json(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text("not valid json {{{")
        assert orch.should_auto_resume(str(state_file)) is False

    def test_returns_false_when_no_final_status_key(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"version": 1}))
        assert orch.should_auto_resume(str(state_file)) is False


class TestMainAutoResumeIntegration:
    """Integration test: main() auto-resumes from RUNNING state with RESUME=0
    and no PROMPT/PROMPT_FILE set."""

    def _make_state(self, tmp_path, final_status="RUNNING", phase="done"):
        prompt = (
            "*** ORIGINAL EXPLORE SUMMARY ***\n"
            "Explore content.\n"
            "*** SCENARIO TEST ***\n"
            "Test content."
        )
        state = {
            "version": 1,
            "final_status": final_status,
            "current_round": 1,
            "current_phase": phase,
            "session_name": "cao-auto",
            "prompt": prompt,
            "terminals": {
                "analyst": "a1", "peer_analyst": "a2",
                "programmer": "p1", "peer_programmer": "p2",
                "tester": "t1",
            },
            "feedback": "None yet.",
            "analyst_feedback": "None yet.",
            "programmer_feedback": "None yet.",
            "outputs": {
                "analyst": "", "analyst_review": "",
                "programmer": "", "programmer_review": "",
                "tester": "",
            },
        }
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))
        return str(state_file)

    @patch("run_orchestrator_loop.verify_resume_terminals")
    @patch("run_orchestrator_loop.load_state")
    @patch("run_orchestrator_loop.should_auto_resume", return_value=True)
    @patch("run_orchestrator_loop.load_config")
    @patch("run_orchestrator_loop._apply_config")
    @patch("run_orchestrator_loop.ApiClient")
    def test_main_auto_resumes_without_prompt_env(
        self, mock_api_cls, mock_apply, mock_load_cfg, mock_auto, mock_load, mock_verify, tmp_path
    ):
        """RESUME=0, no PROMPT, but state file is RUNNING → main() loads
        prompt from state and enters resume path."""
        state_file = self._make_state(tmp_path, "RUNNING", "done")

        # load_config returns a dummy config (main() applies it)
        mock_load_cfg.return_value = {}
        mock_api_cls.return_value = orch.api  # keep existing api mock

        # load_state returns True and populates globals from state
        def fake_load():
            orch.current_phase = "done"
            orch.final_status = "PASS"
            # Load prompt from state file (simulating what load_state does)
            data = json.loads(Path(state_file).read_text())
            orch.PROMPT = data["prompt"]
            return True
        mock_load.side_effect = fake_load

        orig_state = orch.STATE_FILE
        orig_resume = orch.RESUME
        orig_prompt = orch.PROMPT
        orig_prompt_file = orch.PROMPT_FILE
        try:
            orch.STATE_FILE = state_file
            orch.RESUME = False
            orch.PROMPT = ""
            orch.PROMPT_FILE = ""

            with pytest.raises(SystemExit) as exc_info:
                orch.main()

            # Should have auto-resumed (should_auto_resume called with state file)
            mock_auto.assert_called_once_with(state_file)
            # Should have loaded state
            mock_load.assert_called_once()
            # Should have verified terminals
            mock_verify.assert_called_once()
            # Phase=done + PASS → exit 0
            assert exc_info.value.code == 0
        finally:
            orch.STATE_FILE = orig_state
            orch.RESUME = orig_resume
            orch.PROMPT = orig_prompt
            orch.PROMPT_FILE = orig_prompt_file

    @patch("run_orchestrator_loop.load_config", return_value={})
    @patch("run_orchestrator_loop._apply_config")
    @patch("run_orchestrator_loop.ApiClient")
    def test_main_exits_on_empty_prompt_when_no_auto_resume(
        self, mock_api_cls, mock_apply, mock_load_cfg, tmp_path
    ):
        """RESUME=0, no PROMPT, state file has PASS → no auto-resume →
        exits with 'PROMPT is empty' error."""
        state_file = self._make_state(tmp_path, "PASS", "done")
        mock_api_cls.return_value = orch.api

        orig_state = orch.STATE_FILE
        orig_resume = orch.RESUME
        orig_prompt = orch.PROMPT
        orig_prompt_file = orch.PROMPT_FILE
        try:
            orch.STATE_FILE = state_file
            orch.RESUME = False
            orch.PROMPT = ""
            orch.PROMPT_FILE = ""

            with pytest.raises(SystemExit) as exc_info:
                orch.main()
            assert exc_info.value.code == 1
        finally:
            orch.STATE_FILE = orig_state
            orch.RESUME = orig_resume
            orch.PROMPT = orig_prompt
            orch.PROMPT_FILE = orig_prompt_file


# ── JSON config loading (tasks 1.4) ─────────────────────────────────────────


class TestLoadConfig:
    def test_json_overrides_default(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"limits": {"max_rounds": 3}}))
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["MAX_ROUNDS"] == 3

    def test_env_var_overrides_json(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"limits": {"max_rounds": 3}}))
        monkeypatch.setenv("MAX_ROUNDS", "5")
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["MAX_ROUNDS"] == 5

    def test_empty_env_var_treated_as_unset(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"limits": {"max_rounds": 3}}))
        monkeypatch.setenv("MAX_ROUNDS", "")
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["MAX_ROUNDS"] == 3

    def test_empty_env_var_on_boolean_treated_as_unset(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"cleanup_on_exit": True}))
        monkeypatch.setenv("CLEANUP_ON_EXIT", "")
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["CLEANUP_ON_EXIT"] is True

    def test_missing_file_exits_with_error(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            orch.load_config(argv=["prog", str(tmp_path / "missing.json")])
        assert exc_info.value.code == 1

    def test_invalid_json_exits_with_error(self, tmp_path):
        cfg_file = tmp_path / "bad.json"
        cfg_file.write_text("not valid json {{{")
        with pytest.raises(SystemExit) as exc_info:
            orch.load_config(argv=["prog", str(cfg_file)])
        assert exc_info.value.code == 1

    def test_unknown_top_level_key_fatal(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"descripion": "typo", "limits": {"max_rounds": 3}}))
        with pytest.raises(SystemExit) as exc_info:
            orch.load_config(argv=["prog", str(cfg_file)])
        assert exc_info.value.code == 1

    def test_unknown_agent_role_fatal(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"agents": {"peer_anlyst": {"provider": "codex"}}}))
        with pytest.raises(SystemExit) as exc_info:
            orch.load_config(argv=["prog", str(cfg_file)])
        assert exc_info.value.code == 1

    def test_invalid_per_agent_provider_fatal(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"agents": {"analyst": {"provider": "gpt4"}}}))
        with pytest.raises(SystemExit) as exc_info:
            orch.load_config(argv=["prog", str(cfg_file)])
        assert exc_info.value.code == 1

    def test_invalid_top_level_provider_fatal(self, tmp_path):
        """Top-level provider validated even when all agents override it."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "provider": "bad_provider",
            "agents": {
                "analyst": {"provider": "codex"},
                "peer_analyst": {"provider": "codex"},
                "programmer": {"provider": "codex"},
                "peer_programmer": {"provider": "codex"},
                "tester": {"provider": "codex"},
            },
        }))
        with pytest.raises(SystemExit) as exc_info:
            orch.load_config(argv=["prog", str(cfg_file)])
        assert exc_info.value.code == 1

    def test_no_config_file_uses_env_only(self, monkeypatch):
        monkeypatch.setenv("MAX_ROUNDS", "5")
        cfg = orch.load_config(argv=["prog"])
        assert cfg["MAX_ROUNDS"] == 5

    def test_default_config_values(self):
        cfg = orch.load_config(argv=["prog"])
        assert cfg["MAX_ROUNDS"] == 8
        assert cfg["MAX_REVIEW_CYCLES"] == 3
        assert cfg["POLL_SECONDS"] == 2
        assert cfg["MIN_REVIEW_CYCLES_BEFORE_APPROVAL"] == 2
        assert cfg["REVIEW_EVIDENCE_MIN_MATCH"] == 3
        assert cfg["STATE_FILE"].endswith(".tmp/agnostic-3agents-loop-state.json")

    def test_nested_condensation_mapping(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "condensation": {"condense_cross_phase": False, "max_cross_phase_lines": 20}
        }))
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["CONDENSE_CROSS_PHASE"] is False
        assert cfg["MAX_CROSS_PHASE_LINES"] == 20

    def test_nested_handoff_mapping(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "handoff": {"strict_file_handoff": False, "idle_grace_seconds": 60}
        }))
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["STRICT_FILE_HANDOFF"] is False
        assert cfg["IDLE_GRACE_SECONDS"] == 60


# ── Per-agent provider (tasks 2.4) ──────────────────────────────────────────


class TestAgentConfig:
    def test_mixed_providers_in_agent_config(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "agents": {
                "analyst": {"provider": "claude_code"},
                "peer_analyst": {"provider": "codex"},
            }
        }))
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        ac = cfg["_agent_config"]
        assert ac["analyst"]["provider"] == "claude_code"
        assert ac["peer_analyst"]["provider"] == "codex"

    def test_missing_agent_provider_inherits_top_level(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "provider": "claude_code",
            "agents": {"analyst": {"profile": "custom_analyst"}}
        }))
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        ac = cfg["_agent_config"]
        assert ac["analyst"]["provider"] == "claude_code"
        assert ac["analyst"]["profile"] == "custom_analyst"

    def test_missing_profile_uses_role_default(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "agents": {"analyst": {"provider": "codex"}}
        }))
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        ac = cfg["_agent_config"]
        assert ac["analyst"]["profile"] == "system_analyst"

    def test_agents_section_omitted_uses_all_defaults(self):
        cfg = orch.load_config(argv=["prog"])
        ac = cfg["_agent_config"]
        assert ac["analyst"]["profile"] == "system_analyst"
        assert ac["peer_analyst"]["profile"] == "peer_system_analyst"
        assert ac["programmer"]["profile"] == "programmer"
        assert ac["peer_programmer"]["profile"] == "peer_programmer"
        assert ac["tester"]["profile"] == "tester"
        for role in ac:
            assert ac[role]["provider"] == "codex"


# ── Terminal rename (tasks 3.3) ─────────────────────────────────────────────


class TestRenameTerminal:
    @patch.object(orch.api, "get_status", return_value="idle")
    @patch.object(orch.api, "send_input")
    def test_rename_sent_with_correct_format(self, mock_send, mock_status):
        orch._rename_terminal("da33cf00", "analyst")
        mock_send.assert_called_once_with("da33cf00", "/rename analyst-da33cf00")

    @patch.object(orch.api, "get_status", return_value="idle")
    @patch.object(orch.api, "send_input")
    def test_rename_peer_analyst_underscore_format(self, mock_send, mock_status):
        orch._rename_terminal("fae0481d", "peer_analyst")
        mock_send.assert_called_once_with("fae0481d", "/rename peer_analyst-fae0481d")

    @patch.object(orch.api, "send_input", side_effect=Exception("connection error"))
    def test_rename_failure_is_non_fatal(self, mock_send):
        # Should not raise
        orch._rename_terminal("da33cf00", "analyst")

    @patch.object(orch.api, "get_status", return_value="processing")
    @patch.object(orch.api, "send_input")
    @patch("run_orchestrator_loop.time")
    def test_rename_timeout_is_non_fatal(self, mock_time, mock_send, mock_status):
        mock_time.monotonic.side_effect = [0.0, 6.0]
        mock_time.sleep = MagicMock()
        # Should not raise
        orch._rename_terminal("da33cf00", "analyst")


# ── Partial creation cleanup (tasks 4.2) ────────────────────────────────────


class TestPartialCreationCleanup:
    @patch.object(orch.api, "exit_terminal")
    @patch.object(orch.api, "send_input")
    @patch.object(orch.api, "get_status", return_value="idle")
    @patch.object(orch.api, "create_terminal")
    @patch.object(orch.api, "create_session")
    def test_cleanup_on_third_terminal_failure(
        self, mock_session, mock_terminal, mock_status, mock_send, mock_exit
    ):
        mock_session.return_value = {"id": "t1", "session_name": "cao-test"}
        mock_terminal.side_effect = [
            {"id": "t2"},
            Exception("creation failed"),
        ]

        with pytest.raises(SystemExit) as exc_info:
            orch.init_new_run()
        assert exc_info.value.code == 1

        exit_calls = [c[0][0] for c in mock_exit.call_args_list]
        assert "t1" in exit_calls
        assert "t2" in exit_calls


# ── Explore-before-ff on retry (tasks 5.2) ──────────────────────────────────


class TestExploreBeforeFf:
    def setup_method(self):
        orch._explore_sent.clear()
        orch.EXPLORE_SUMMARY = "Explore summary text."
        orch.terminal_ids.update({
            "analyst": "a001", "peer_analyst": "a002",
            "programmer": "p001", "peer_programmer": "p002", "tester": "t001",
        })
        orch.feedback = "RESULT: FAIL\nTests failed."
        orch.analyst_feedback = "None yet."

    def test_round_1_has_explore_codebase(self):
        prompt = orch.build_analyst_prompt(1, 1)
        assert "Explore the codebase" in prompt
        assert "fast-forward skill" in prompt

    def test_round_2_has_explore_skill_investigate(self):
        prompt = orch.build_analyst_prompt(2, 1)
        assert "explore skill to investigate the test failure" in prompt
        assert "fast-forward skill to update" in prompt
        assert "Explore the codebase" not in prompt


# ── State file per-agent provider (tasks 6.4) ───────────────────────────────


class TestStateFilePerAgentProvider:
    def test_state_roundtrip_with_mixed_providers(self, tmp_path):
        state_file = str(tmp_path / "state.json")
        orig_state = orch.STATE_FILE
        orig_agent = orch.AGENT_CONFIG.copy()
        try:
            orch.STATE_FILE = state_file
            orch.AGENT_CONFIG = {
                "analyst": {"provider": "claude_code", "profile": "system_analyst"},
                "peer_analyst": {"provider": "codex", "profile": "peer_system_analyst"},
                "programmer": {"provider": "claude_code", "profile": "programmer"},
                "peer_programmer": {"provider": "codex", "profile": "peer_programmer"},
                "tester": {"provider": "codex", "profile": "tester"},
            }
            orch.terminal_ids.update({
                "analyst": "aa11", "peer_analyst": "bb22",
                "programmer": "cc33", "peer_programmer": "dd44", "tester": "ee55",
            })
            orch.save_state()

            data = json.loads(Path(state_file).read_text())
            assert data["terminals"]["analyst"] == {"id": "aa11", "provider": "claude_code"}
            assert data["terminals"]["peer_analyst"] == {"id": "bb22", "provider": "codex"}

            for k in orch.terminal_ids:
                orch.terminal_ids[k] = ""
            orch.load_state()
            assert orch.terminal_ids["analyst"] == "aa11"
            assert orch.terminal_ids["peer_analyst"] == "bb22"
        finally:
            orch.STATE_FILE = orig_state
            orch.AGENT_CONFIG = orig_agent

    def test_old_format_state_file_loads_correctly(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "provider": "codex",
            "session_name": "cao-old",
            "current_round": 2,
            "current_phase": "programmer",
            "final_status": "RUNNING",
            "terminals": {
                "analyst": "da33cf00",
                "peer_analyst": "fae0481d",
                "programmer": "abc12345",
                "peer_programmer": "def67890",
                "tester": "99887766",
            },
            "feedback": "test feedback",
            "analyst_feedback": "",
            "programmer_feedback": "",
            "outputs": {},
        }))
        orig_state = orch.STATE_FILE
        try:
            orch.STATE_FILE = str(state_file)
            assert orch.load_state() is True
            assert orch.terminal_ids["analyst"] == "da33cf00"
            assert orch.terminal_ids["peer_analyst"] == "fae0481d"
        finally:
            orch.STATE_FILE = orig_state

    @patch.object(orch.api, "get_status", return_value="idle")
    def test_old_format_provider_mismatch_detected(self, mock_status, tmp_path, capsys):
        """Old-format terminals are normalized with state-level provider,
        so verify_resume_terminals can detect provider mismatches."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "provider": "codex",
            "terminals": {
                "analyst": "da33cf00",
                "peer_analyst": "fae0481d",
                "programmer": "abc12345",
                "peer_programmer": "def67890",
                "tester": "99887766",
            },
        }))
        orig_state = orch.STATE_FILE
        orig_agent = orch.AGENT_CONFIG.copy()
        try:
            orch.STATE_FILE = str(state_file)
            # Load normalizes old strings to {"id": ..., "provider": "codex"}
            assert orch.load_state() is True
            # Change analyst config to a different provider
            orch.AGENT_CONFIG["analyst"] = {"provider": "claude_code", "profile": "system_analyst"}
            orch.verify_resume_terminals()
            captured = capsys.readouterr()
            assert "provider mismatch" in captured.out
            assert "analyst" in captured.out
        finally:
            orch.STATE_FILE = orig_state
            orch.AGENT_CONFIG = orig_agent

    @patch.object(orch.api, "get_status")
    def test_unreachable_terminal_on_resume_exits(self, mock_status, tmp_path):
        terminals_data = {
            "analyst": {"id": "t1", "provider": "codex"},
            "peer_analyst": {"id": "t2", "provider": "codex"},
            "programmer": {"id": "t3", "provider": "codex"},
            "peer_programmer": {"id": "t4", "provider": "codex"},
            "tester": {"id": "t5", "provider": "codex"},
        }
        orig_loaded = orch._loaded_state_terminals
        try:
            orch._loaded_state_terminals = terminals_data
            orch.terminal_ids.update({
                "analyst": "t1", "peer_analyst": "t2", "programmer": "t3",
                "peer_programmer": "t4", "tester": "t5",
            })
            mock_status.side_effect = httpx.HTTPError("unreachable")
            with pytest.raises(SystemExit) as exc_info:
                orch.verify_resume_terminals()
            assert exc_info.value.code == 1
        finally:
            orch._loaded_state_terminals = orig_loaded

    @patch.object(orch.api, "get_status", return_value="idle")
    def test_provider_mismatch_on_resume_logs_warning(self, mock_status, tmp_path, capsys):
        terminals_data = {
            "analyst": {"id": "t1", "provider": "codex"},
            "peer_analyst": {"id": "t2", "provider": "codex"},
            "programmer": {"id": "t3", "provider": "codex"},
            "peer_programmer": {"id": "t4", "provider": "codex"},
            "tester": {"id": "t5", "provider": "codex"},
        }
        orig_loaded = orch._loaded_state_terminals
        orig_agent = orch.AGENT_CONFIG.copy()
        try:
            orch._loaded_state_terminals = terminals_data
            orch.terminal_ids.update({
                "analyst": "t1", "peer_analyst": "t2", "programmer": "t3",
                "peer_programmer": "t4", "tester": "t5",
            })
            orch.AGENT_CONFIG["analyst"] = {"provider": "claude_code", "profile": "system_analyst"}
            orch.verify_resume_terminals()
            captured = capsys.readouterr()
            assert "provider mismatch" in captured.out
            assert "analyst" in captured.out
        finally:
            orch._loaded_state_terminals = orig_loaded
            orch.AGENT_CONFIG = orig_agent


# ── Start agent selection (tasks 7.5) ────────────────────────────────────────


class TestStartAgentSelection:
    """Tests for START_AGENT feature (tasks 7.1-7.5)."""

    # ── Config tests ──

    def test_default_start_agent_is_analyst(self):
        cfg = orch.load_config(argv=["prog"])
        assert cfg["START_AGENT"] == "analyst"

    def test_start_agent_from_json(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"start_agent": "tester"}))
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["START_AGENT"] == "tester"

    def test_start_agent_env_overrides_json(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"start_agent": "tester"}))
        monkeypatch.setenv("START_AGENT", "programmer")
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["START_AGENT"] == "programmer"

    def test_invalid_start_agent_exits(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"start_agent": "invalid_role"}))
        with pytest.raises(SystemExit) as exc_info:
            orch.load_config(argv=["prog", str(cfg_file)])
        assert exc_info.value.code == 1

    # ── init_new_run phase mapping tests ──

    def _mock_init_apis(self, mock_session, mock_terminal):
        mock_session.return_value = {"id": "t1", "session_name": "cao-test"}
        mock_terminal.side_effect = [{"id": f"t{i}"} for i in range(2, 6)]

    @patch("run_orchestrator_loop._rename_terminal")
    @patch.object(orch.api, "get_status", return_value="idle")
    @patch.object(orch.api, "create_terminal")
    @patch.object(orch.api, "create_session")
    def test_init_default_starts_at_analyst_phase(
        self, mock_session, mock_terminal, mock_status, mock_rename, tmp_path
    ):
        self._mock_init_apis(mock_session, mock_terminal)
        orig = (orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer)
        try:
            orch.START_AGENT = "analyst"
            orch.STATE_FILE = str(tmp_path / "state.json")
            orch.init_new_run()
            assert orch.current_phase == orch.PHASE_ANALYST
            assert orch.outputs["analyst"] == ""
            assert orch.outputs["programmer"] == ""
            assert orch._start_at_peer is False
        finally:
            orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer = orig

    @patch("run_orchestrator_loop._rename_terminal")
    @patch.object(orch.api, "get_status", return_value="idle")
    @patch.object(orch.api, "create_terminal")
    @patch.object(orch.api, "create_session")
    def test_init_start_at_peer_analyst(
        self, mock_session, mock_terminal, mock_status, mock_rename, tmp_path
    ):
        self._mock_init_apis(mock_session, mock_terminal)
        orig = (orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer)
        try:
            orch.START_AGENT = "peer_analyst"
            orch.STATE_FILE = str(tmp_path / "state.json")
            orch.init_new_run()
            assert orch.current_phase == orch.PHASE_ANALYST
            assert orch.outputs["analyst"] == orch._UPSTREAM_PLACEHOLDER
            assert orch._start_at_peer is True
        finally:
            orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer = orig

    @patch("run_orchestrator_loop._rename_terminal")
    @patch.object(orch.api, "get_status", return_value="idle")
    @patch.object(orch.api, "create_terminal")
    @patch.object(orch.api, "create_session")
    def test_init_start_at_programmer(
        self, mock_session, mock_terminal, mock_status, mock_rename, tmp_path
    ):
        self._mock_init_apis(mock_session, mock_terminal)
        orig = (orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer)
        try:
            orch.START_AGENT = "programmer"
            orch.STATE_FILE = str(tmp_path / "state.json")
            orch.init_new_run()
            assert orch.current_phase == orch.PHASE_PROGRAMMER
            assert orch.outputs["analyst"] == orch._UPSTREAM_PLACEHOLDER
            assert orch.outputs["programmer"] == ""
            assert orch._start_at_peer is False
        finally:
            orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer = orig

    @patch("run_orchestrator_loop._rename_terminal")
    @patch.object(orch.api, "get_status", return_value="idle")
    @patch.object(orch.api, "create_terminal")
    @patch.object(orch.api, "create_session")
    def test_init_start_at_peer_programmer(
        self, mock_session, mock_terminal, mock_status, mock_rename, tmp_path
    ):
        self._mock_init_apis(mock_session, mock_terminal)
        orig = (orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer)
        try:
            orch.START_AGENT = "peer_programmer"
            orch.STATE_FILE = str(tmp_path / "state.json")
            orch.init_new_run()
            assert orch.current_phase == orch.PHASE_PROGRAMMER
            assert orch.outputs["analyst"] == orch._UPSTREAM_PLACEHOLDER
            assert orch.outputs["programmer"] == orch._UPSTREAM_PLACEHOLDER
            assert orch._start_at_peer is True
        finally:
            orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer = orig

    @patch("run_orchestrator_loop._rename_terminal")
    @patch.object(orch.api, "get_status", return_value="idle")
    @patch.object(orch.api, "create_terminal")
    @patch.object(orch.api, "create_session")
    def test_init_start_at_tester(
        self, mock_session, mock_terminal, mock_status, mock_rename, tmp_path
    ):
        self._mock_init_apis(mock_session, mock_terminal)
        orig = (orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer)
        try:
            orch.START_AGENT = "tester"
            orch.STATE_FILE = str(tmp_path / "state.json")
            orch.init_new_run()
            assert orch.current_phase == orch.PHASE_TESTER
            assert orch.outputs["programmer"] == orch._UPSTREAM_PLACEHOLDER
            assert orch._start_at_peer is False
        finally:
            orch.START_AGENT, orch.STATE_FILE, orch._start_at_peer = orig

    # ── Resume ignores START_AGENT ──

    def test_resume_ignores_start_agent(self, tmp_path):
        """Resume uses current_phase from state file, not START_AGENT."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "session_name": "cao-resume",
            "current_round": 2,
            "current_phase": "analyst",
            "final_status": "RUNNING",
            "terminals": {
                "analyst": {"id": "a1", "provider": "codex"},
                "peer_analyst": {"id": "a2", "provider": "codex"},
                "programmer": {"id": "p1", "provider": "codex"},
                "peer_programmer": {"id": "p2", "provider": "codex"},
                "tester": {"id": "t1", "provider": "codex"},
            },
            "feedback": "test feedback",
            "analyst_feedback": "",
            "programmer_feedback": "",
            "outputs": {},
        }))
        orig = (orch.STATE_FILE, orch.START_AGENT, orch._start_at_peer)
        try:
            orch.STATE_FILE = str(state_file)
            orch.START_AGENT = "tester"  # Should be ignored on resume
            orch._start_at_peer = False
            assert orch.load_state() is True
            # Phase comes from state file, not START_AGENT
            assert orch.current_phase == orch.PHASE_ANALYST
            # _start_at_peer remains False (load_state doesn't touch it)
            assert orch._start_at_peer is False
        finally:
            orch.STATE_FILE, orch.START_AGENT, orch._start_at_peer = orig

    # ── Peer first-dispatch behavior (integration tests) ──

    def _save_globals(self):
        """Save module globals that main loop tests modify."""
        keys = [
            "START_AGENT", "MAX_ROUNDS", "MAX_REVIEW_CYCLES",
            "MIN_REVIEW_CYCLES_BEFORE_APPROVAL", "PROMPT", "PROMPT_FILE",
            "RESUME", "STATE_FILE", "_start_at_peer", "current_round",
            "current_phase", "final_status", "feedback",
            "analyst_feedback", "programmer_feedback",
        ]
        saved = {k: getattr(orch, k) for k in keys}
        saved["outputs"] = orch.outputs.copy()
        saved["terminal_ids"] = orch.terminal_ids.copy()
        saved["_explore_sent"] = orch._explore_sent.copy()
        return saved

    def _restore_globals(self, saved):
        for k, v in saved.items():
            if k == "outputs":
                orch.outputs.update(v)
            elif k == "terminal_ids":
                orch.terminal_ids.update(v)
            elif k == "_explore_sent":
                orch._explore_sent.clear()
                orch._explore_sent.update(v)
            else:
                setattr(orch, k, v)

    @patch("run_orchestrator_loop.cleanup")
    @patch("run_orchestrator_loop.save_state")
    @patch("run_orchestrator_loop.send_and_wait")
    @patch("run_orchestrator_loop.ensure_response_dir")
    @patch("run_orchestrator_loop.init_new_run")
    @patch("run_orchestrator_loop.load_config")
    @patch("run_orchestrator_loop._apply_config")
    @patch("run_orchestrator_loop.ApiClient")
    def test_peer_analyst_first_dispatch_skips_analyst(
        self, mock_api_cls, mock_apply, mock_load_cfg,
        mock_init, mock_ensure, mock_send, mock_save, mock_cleanup
    ):
        """START_AGENT=peer_analyst: analyst dispatch skipped, peer review happens."""
        mock_load_cfg.return_value = {}
        mock_api_cls.return_value = orch.api

        def fake_init():
            orch.session_name = "cao-test"
            orch.terminal_ids.update({
                "analyst": "a1", "peer_analyst": "pa1",
                "programmer": "p1", "peer_programmer": "pp1", "tester": "t1",
            })
            orch.current_round = 1
            orch.current_phase = orch.PHASE_ANALYST
            orch._start_at_peer = True
            orch.outputs["analyst"] = orch._UPSTREAM_PLACEHOLDER
            for k in ["analyst_review", "programmer", "programmer_review", "tester"]:
                orch.outputs[k] = ""
            orch.final_status = "RUNNING"
            orch.feedback = "None yet."
            orch.analyst_feedback = "None yet."
            orch.programmer_feedback = "None yet."
        mock_init.side_effect = fake_init

        mock_send.side_effect = [
            "REVIEW_RESULT: REVISE\nREVIEW_NOTES: needs work",
            "PROGRAMMER_SUMMARY:\n- Files changed: x.py",
            textwrap.dedent("""\
                REVIEW_RESULT: APPROVED
                REVIEW_NOTES:
                - Implementation code changes look correct.
                - Validation test command runs clean.
                - Risk of regression is low, quality coverage adequate.
                - No remaining issues found.
            """),
            "RESULT: PASS\nEVIDENCE: all tests passed",
        ]

        saved = self._save_globals()
        try:
            orch.START_AGENT = "peer_analyst"
            orch.MAX_ROUNDS = 1
            orch.MAX_REVIEW_CYCLES = 1
            orch.MIN_REVIEW_CYCLES_BEFORE_APPROVAL = 1
            orch.PROMPT = (
                "*** ORIGINAL EXPLORE SUMMARY ***\n"
                "Explore content.\n"
                "*** SCENARIO TEST ***\n"
                "Test content."
            )
            orch.PROMPT_FILE = ""
            orch.RESUME = False
            orch.STATE_FILE = "/tmp/nonexistent-test-start-agent.json"
            orch._explore_sent.clear()

            with pytest.raises(SystemExit) as exc_info:
                orch.main()
            assert exc_info.value.code == 0

            call_roles = [c[0][1] for c in mock_send.call_args_list]
            assert "analyst" not in call_roles  # Skipped!
            assert "analyst_review" in call_roles
            assert "programmer" in call_roles
            assert "tester" in call_roles
        finally:
            self._restore_globals(saved)

    @patch("run_orchestrator_loop.cleanup")
    @patch("run_orchestrator_loop.save_state")
    @patch("run_orchestrator_loop.send_and_wait")
    @patch("run_orchestrator_loop.ensure_response_dir")
    @patch("run_orchestrator_loop.init_new_run")
    @patch("run_orchestrator_loop.load_config")
    @patch("run_orchestrator_loop._apply_config")
    @patch("run_orchestrator_loop.ApiClient")
    def test_peer_programmer_first_dispatch_skips_programmer(
        self, mock_api_cls, mock_apply, mock_load_cfg,
        mock_init, mock_ensure, mock_send, mock_save, mock_cleanup
    ):
        """START_AGENT=peer_programmer: programmer dispatch skipped, peer review happens."""
        mock_load_cfg.return_value = {}
        mock_api_cls.return_value = orch.api

        def fake_init():
            orch.session_name = "cao-test"
            orch.terminal_ids.update({
                "analyst": "a1", "peer_analyst": "pa1",
                "programmer": "p1", "peer_programmer": "pp1", "tester": "t1",
            })
            orch.current_round = 1
            orch.current_phase = orch.PHASE_PROGRAMMER
            orch._start_at_peer = True
            orch.outputs["analyst"] = orch._UPSTREAM_PLACEHOLDER
            orch.outputs["programmer"] = orch._UPSTREAM_PLACEHOLDER
            for k in ["analyst_review", "programmer_review", "tester"]:
                orch.outputs[k] = ""
            orch.final_status = "RUNNING"
            orch.feedback = "None yet."
            orch.analyst_feedback = "None yet."
            orch.programmer_feedback = "None yet."
        mock_init.side_effect = fake_init

        mock_send.side_effect = [
            "REVIEW_RESULT: REVISE\nREVIEW_NOTES: needs work",
            "RESULT: PASS\nEVIDENCE: all tests passed",
        ]

        saved = self._save_globals()
        try:
            orch.START_AGENT = "peer_programmer"
            orch.MAX_ROUNDS = 1
            orch.MAX_REVIEW_CYCLES = 1
            orch.MIN_REVIEW_CYCLES_BEFORE_APPROVAL = 1
            orch.PROMPT = (
                "*** ORIGINAL EXPLORE SUMMARY ***\n"
                "Explore content.\n"
                "*** SCENARIO TEST ***\n"
                "Test content."
            )
            orch.PROMPT_FILE = ""
            orch.RESUME = False
            orch.STATE_FILE = "/tmp/nonexistent-test-start-agent.json"
            orch._explore_sent.clear()

            with pytest.raises(SystemExit) as exc_info:
                orch.main()
            assert exc_info.value.code == 0

            call_roles = [c[0][1] for c in mock_send.call_args_list]
            assert "analyst" not in call_roles
            assert "analyst_review" not in call_roles
            assert "programmer" not in call_roles  # Skipped!
            assert "programmer_review" in call_roles
            assert "tester" in call_roles
        finally:
            self._restore_globals(saved)


# ── improve-fail-handoff: extract_test_evidence with MAX_TEST_EVIDENCE_LINES ──


class TestExtractTestEvidenceLimit:
    """Tests for split line limits: MAX_TEST_EVIDENCE_LINES vs MAX_FEEDBACK_LINES."""

    def test_truncates_at_max_test_evidence_lines(self):
        """6.1: extract_test_evidence truncates at MAX_TEST_EVIDENCE_LINES, not MAX_FEEDBACK_LINES."""
        original_tel = orch.MAX_TEST_EVIDENCE_LINES
        original_mfl = orch.MAX_FEEDBACK_LINES
        try:
            orch.MAX_TEST_EVIDENCE_LINES = 120
            orch.MAX_FEEDBACK_LINES = 30
            lines = ["RESULT: FAIL", "EVIDENCE:"] + [f"line {i}" for i in range(200)]
            text = "\n".join(lines)
            result = orch.extract_test_evidence(text)
            result_lines = result.splitlines()
            assert len(result_lines) == 120
            assert len(result_lines) > 30  # Must exceed MAX_FEEDBACK_LINES
        finally:
            orch.MAX_TEST_EVIDENCE_LINES = original_tel
            orch.MAX_FEEDBACK_LINES = original_mfl

    def test_fallback_uses_max_test_evidence_lines(self):
        """6.2: Fallback path (no markers) uses MAX_TEST_EVIDENCE_LINES."""
        original_tel = orch.MAX_TEST_EVIDENCE_LINES
        original_mfl = orch.MAX_FEEDBACK_LINES
        try:
            orch.MAX_TEST_EVIDENCE_LINES = 120
            orch.MAX_FEEDBACK_LINES = 30
            lines = [f"plain line {i}" for i in range(200)]
            text = "\n".join(lines)
            result = orch.extract_test_evidence(text)
            result_lines = result.splitlines()
            assert len(result_lines) == 120
        finally:
            orch.MAX_TEST_EVIDENCE_LINES = original_tel
            orch.MAX_FEEDBACK_LINES = original_mfl

    def test_review_notes_still_uses_max_feedback_lines(self):
        """6.3: extract_review_notes still truncates at MAX_FEEDBACK_LINES (unchanged)."""
        original_mfl = orch.MAX_FEEDBACK_LINES
        try:
            orch.MAX_FEEDBACK_LINES = 30
            lines = ["REVIEW_NOTES:"] + [f"line {i}" for i in range(100)]
            review = "\n".join(lines)
            result = orch.extract_review_notes(review)
            assert len(result.splitlines()) <= 30
        finally:
            orch.MAX_FEEDBACK_LINES = original_mfl

    def test_custom_non_default_limit(self):
        """6.16: extract_test_evidence truncates at a custom value (e.g. 60)."""
        original_tel = orch.MAX_TEST_EVIDENCE_LINES
        try:
            orch.MAX_TEST_EVIDENCE_LINES = 60
            lines = ["RESULT: FAIL", "EVIDENCE:"] + [f"line {i}" for i in range(200)]
            text = "\n".join(lines)
            result = orch.extract_test_evidence(text)
            assert len(result.splitlines()) == 60
        finally:
            orch.MAX_TEST_EVIDENCE_LINES = original_tel


# ── improve-fail-handoff: programmer_context_for_retry state persistence ──


class TestProgrammerContextForRetryState:
    """Tests for save_state/load_state round-trip of programmer_context_for_retry."""

    def test_roundtrip_preserves_retry_context(self, tmp_path):
        """6.4: save_state/load_state round-trip preserves programmer_context_for_retry."""
        state_file = str(tmp_path / "state.json")
        original_state_file = orch.STATE_FILE
        try:
            orch.STATE_FILE = state_file
            orch.session_name = "cao-retry-test"
            orch.terminal_ids.update({
                "analyst": "a1", "peer_analyst": "a2",
                "programmer": "p1", "peer_programmer": "p2", "tester": "t1",
            })
            orch.current_round = 2
            orch.current_phase = orch.PHASE_ANALYST
            orch.final_status = "RUNNING"
            orch.feedback = "RESULT: FAIL"
            orch.analyst_feedback = "None yet."
            orch.programmer_feedback = "None yet."
            orch.programmer_context_for_retry = "- Files changed: foo.py\n- Behavior implemented: bar"
            orch.outputs.update({
                "analyst": "", "analyst_review": "",
                "programmer": "", "programmer_review": "", "tester": "",
            })

            orch.save_state()

            # Reset and reload
            orch.programmer_context_for_retry = ""
            assert orch.load_state() is True
            assert orch.programmer_context_for_retry == "- Files changed: foo.py\n- Behavior implemented: bar"
        finally:
            orch.STATE_FILE = original_state_file

    def test_load_old_state_defaults_to_empty(self, tmp_path):
        """6.5: load_state on old state file without programmer_context_for_retry defaults to ''."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "current_round": 2,
            "current_phase": "analyst",
            "terminals": {},
            "outputs": {},
            "feedback": "RESULT: FAIL",
            "analyst_feedback": "None yet.",
            "programmer_feedback": "None yet.",
        }))
        original_state_file = orch.STATE_FILE
        try:
            orch.STATE_FILE = str(state_file)
            orch.programmer_context_for_retry = "should be overwritten"
            orch.load_state()
            assert orch.programmer_context_for_retry == ""
        finally:
            orch.STATE_FILE = original_state_file


# ── improve-fail-handoff: analyst prompt includes/excludes retry context ──


class TestAnalystPromptRetryContext:
    """Tests for programmer_context_for_retry injection in build_analyst_prompt."""

    def setup_method(self):
        orch._explore_sent.clear()
        orch.EXPLORE_SUMMARY = "Explore summary text."
        orch.SCENARIO_TEST = "Run the test scenario."
        orch.terminal_ids.update({
            "analyst": "a001", "peer_analyst": "a002",
            "programmer": "p001", "peer_programmer": "p002", "tester": "t001",
        })
        orch.feedback = "RESULT: FAIL\nEVIDENCE:\n- something broke"
        orch.analyst_feedback = "None yet."
        orch.programmer_feedback = "None yet."

    def test_round2_includes_context_when_nonempty(self):
        """6.6: build_analyst_prompt includes programmer context when round > 1 and non-empty."""
        orch.programmer_context_for_retry = "- Files changed: foo.py"
        prompt = orch.build_analyst_prompt(2, 1)
        assert "Previous round programmer changes (context only):" in prompt
        assert "- Files changed: foo.py" in prompt

    def test_round1_excludes_context(self):
        """6.7: build_analyst_prompt excludes programmer context when round == 1."""
        orch.programmer_context_for_retry = "- Files changed: foo.py"
        prompt = orch.build_analyst_prompt(1, 1)
        assert "Previous round programmer changes" not in prompt

    def test_round2_excludes_context_when_empty(self):
        """6.8: build_analyst_prompt excludes block when context is empty string."""
        orch.programmer_context_for_retry = ""
        prompt = orch.build_analyst_prompt(2, 1)
        assert "Previous round programmer changes" not in prompt


# ── improve-fail-handoff: other prompts never include retry context ──


class TestOtherPromptsExcludeRetryContext:
    """Tests that non-analyst prompt builders never include programmer retry context."""

    def setup_method(self):
        orch._explore_sent.clear()
        orch.EXPLORE_SUMMARY = "Explore summary text."
        orch.SCENARIO_TEST = "Run the test scenario."
        orch.terminal_ids.update({
            "analyst": "a001", "peer_analyst": "a002",
            "programmer": "p001", "peer_programmer": "p002", "tester": "t001",
        })
        orch.feedback = "None yet."
        orch.analyst_feedback = "None yet."
        orch.programmer_feedback = "None yet."
        orch.programmer_context_for_retry = "- Files changed: should_not_appear.py"

    def test_programmer_prompt_excludes(self):
        """6.10: build_programmer_prompt does not contain retry context."""
        prompt = orch.build_programmer_prompt(2, 1, "analyst output")
        assert "Previous round programmer changes" not in prompt

    def test_programmer_review_prompt_excludes(self):
        """6.11: build_programmer_review_prompt does not contain retry context."""
        prompt = orch.build_programmer_review_prompt("programmer output")
        assert "Previous round programmer changes" not in prompt

    def test_analyst_review_prompt_excludes(self):
        """6.12: build_analyst_review_prompt does not contain retry context."""
        prompt = orch.build_analyst_review_prompt("analyst output")
        assert "Previous round programmer changes" not in prompt

    def test_tester_prompt_excludes(self):
        """6.13: build_tester_prompt does not contain retry context."""
        prompt = orch.build_tester_prompt("programmer output")
        assert "Previous round programmer changes" not in prompt


# ── improve-fail-handoff: MAX_TEST_EVIDENCE_LINES config pipeline ──


class TestMaxTestEvidenceLinesConfig:
    """Tests for MAX_TEST_EVIDENCE_LINES in the config pipeline."""

    def test_json_config_loads_test_evidence_lines(self, tmp_path):
        """6.9: MAX_TEST_EVIDENCE_LINES loads from JSON condensation section."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "condensation": {"max_test_evidence_lines": 80}
        }))
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["MAX_TEST_EVIDENCE_LINES"] == 80

    def test_default_value_is_120(self):
        """6.14: MAX_TEST_EVIDENCE_LINES defaults to 120 when not configured."""
        cfg = orch.load_config(argv=["prog"])
        assert cfg["MAX_TEST_EVIDENCE_LINES"] == 120

    def test_env_var_overrides_json(self, tmp_path, monkeypatch):
        """6.15: env var MAX_TEST_EVIDENCE_LINES overrides JSON value."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "condensation": {"max_test_evidence_lines": 80}
        }))
        monkeypatch.setenv("MAX_TEST_EVIDENCE_LINES", "60")
        cfg = orch.load_config(argv=["prog", str(cfg_file)])
        assert cfg["MAX_TEST_EVIDENCE_LINES"] == 60
