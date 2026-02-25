"""Unit tests for Codex provider."""

from pathlib import Path
from unittest.mock import patch

import pytest

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.codex import CodexProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> str:
    with open(FIXTURES_DIR / filename, "r") as f:
        return f.read()


class TestCodexProviderInitialization:
    @patch("cli_agent_orchestrator.providers.codex.wait_until_status")
    @patch("cli_agent_orchestrator.providers.codex.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_initialize_success(self, mock_tmux, mock_wait_shell, mock_wait_status):
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = True

        provider = CodexProvider("test1234", "test-session", "window-0", None)
        result = provider.initialize()

        assert result is True
        mock_wait_shell.assert_called_once()
        mock_tmux.send_keys.assert_called_once_with("test-session", "window-0", "codex")
        mock_wait_status.assert_called_once()

    @patch("cli_agent_orchestrator.providers.codex.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_initialize_shell_timeout(self, mock_tmux, mock_wait_shell):
        mock_wait_shell.return_value = False

        provider = CodexProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(TimeoutError, match="Shell initialization timed out"):
            provider.initialize()

    @patch("cli_agent_orchestrator.providers.codex.wait_until_status")
    @patch("cli_agent_orchestrator.providers.codex.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_initialize_codex_timeout(self, mock_tmux, mock_wait_shell, mock_wait_status):
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = False

        provider = CodexProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(TimeoutError, match="Codex initialization timed out"):
            provider.initialize()


class TestCodexProviderStatusDetection:
    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_idle(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("codex_idle_output.txt")

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_completed(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("codex_completed_output.txt")

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_processing(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("codex_processing_output.txt")

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_waiting_user_answer(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("codex_permission_output.txt")

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_error(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("codex_error_output.txt")

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_empty_output(self, mock_tmux):
        mock_tmux.get_history.return_value = ""

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_with_tail_lines(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("codex_idle_output.txt")

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status(tail_lines=50)

        assert status == TerminalStatus.IDLE
        mock_tmux.get_history.assert_called_once_with("test-session", "window-0", tail_lines=50)

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_processing_when_old_prompt_present(self, mock_tmux):
        # If the captured history contains an earlier prompt but the *latest* output is processing,
        # we should report PROCESSING.
        mock_tmux.get_history.return_value = (
            "Welcome to Codex\n" "❯ \n" "You Fix the failing tests\n" "Codex is thinking…\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_not_error_on_failed_in_message(self, mock_tmux):
        # "failed" is commonly used in normal assistant output; it should not automatically
        # force ERROR.
        mock_tmux.get_history.return_value = (
            "You Explain why the test failed\n"
            "assistant: The test failed because the assertion is incorrect.\n"
            "\n"
            "❯ \n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_idle_if_no_assistant_after_last_user(self, mock_tmux):
        # If there is a user message but no assistant response after it, we should not
        # treat the session as COMPLETED.
        mock_tmux.get_history.return_value = "assistant: Welcome\n" "You Do the thing\n" "\n" "❯ \n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_processing_when_no_prompt_and_no_keywords(self, mock_tmux):
        # Codex output may not always include explicit "thinking/processing" keywords.
        # Without an idle prompt at the end, we should assume it's still processing.
        mock_tmux.get_history.return_value = "You Run the command\nWorking...\n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_not_error_when_assistant_mentions_error_text(self, mock_tmux):
        mock_tmux.get_history.return_value = (
            "You Explain the failure\n"
            "assistant: Here's an example error:\n"
            "Error: example only\n"
            "\n"
            "❯ \n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_not_waiting_when_assistant_mentions_approval_text(self, mock_tmux):
        mock_tmux.get_history.return_value = (
            "You Explain approvals\n"
            "assistant: You might see this prompt:\n"
            "Approve this command? [y/n]\n"
            "\n"
            "❯ \n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_error_when_error_after_user_and_prompt(self, mock_tmux):
        mock_tmux.get_history.return_value = "You Run thing\nError: failed\n\n❯ \n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_waiting_user_answer_when_no_user_prefix(self, mock_tmux):
        mock_tmux.get_history.return_value = "Approve this command? [y/n]\n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_waiting_user_answer_v104_yes_proceed_prompt(self, mock_tmux):
        mock_tmux.get_history.return_value = (
            "You Fix the bug\n"
            "• Reading file src/main.py\n"
            "› 1. Yes, proceed (y)\n"
            "  2. No, and tell Codex what to do differently (esc)\n"
            "\n"
            "  Press enter to confirm or esc to cancel\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_error_when_no_user_prefix(self, mock_tmux):
        mock_tmux.get_history.return_value = "Error: something failed\n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_idle_with_v104_prompt_and_footer(self, mock_tmux):
        mock_tmux.get_history.return_value = "Welcome to Codex\n› Plan the fix\n100% context left\n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_idle_with_inline_shortcuts_and_context_footer(self, mock_tmux):
        mock_tmux.get_history.return_value = (
            "╰──────────────────────────────────────────────────╯\n"
            "Tip: Try the Codex App.\n"
            "› Summarize recent commits\n"
            "? for shortcuts                                            100% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_idle_with_merged_prompt_shortcuts_and_footer(self, mock_tmux):
        # Some captures merge the prompt, shortcut hint, and context footer into one line.
        mock_tmux.get_history.return_value = (
            "• Findings\n"
            "  REVIEW_RESULT: APPROVED\n"
            "›Summarize recent commits? for shortcuts59% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_completed_with_v104_prompt_and_footer(self, mock_tmux):
        mock_tmux.get_history.return_value = (
            "You fix the bug\n"
            "assistant: Done. I updated the matcher.\n"
            "›\n"
            "100% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_completed_with_v104_user_and_assistant_markers(self, mock_tmux):
        mock_tmux.get_history.return_value = (
            "› Reply with READY\n"
            "• READY\n"
            "›\n"
            "100% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_processing_with_v104_markers_without_idle_prompt(self, mock_tmux):
        mock_tmux.get_history.return_value = "› Reply with READY\n• Working on it...\n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_processing_when_footer_and_prompt_hint_present_but_working(self, mock_tmux):
        # Codex v0.104 UI can show prompt hint + context footer while still working.
        mock_tmux.get_history.return_value = (
            "› Reply with READY\n"
            "• Exploring project files\n"
            "Working (12s • esc to interrupt)\n"
            "› Find and fix a bug in @filename\n"
            "? for shortcuts\n"
            "99% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING


    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_idle_despite_narrative_processing_keyword(self, mock_tmux):
        # "running" in narrative text should NOT block idle detection.
        mock_tmux.get_history.return_value = (
            "› Reply with READY\n"
            "• I have all results and will now write the required PASS/FAIL report to the\n"
            "  mandated response file in the exact format, then stop running commands.\n"
            "\n"
            "• RESULT: PASS\n"
            "\n"
            "  Report written to test_result.md.\n"
            "\n"
            "› Explain this codebase\n"
            "? for shortcuts\n"
            "87% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status in (TerminalStatus.IDLE, TerminalStatus.COMPLETED)

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_processing_with_active_work_ui_overrides_idle(self, mock_tmux):
        # "esc to interrupt" UI should still block idle detection.
        mock_tmux.get_history.return_value = (
            "› Reply with READY\n"
            "• READY\n"
            "› Fix the bug\n"
            "• Analyzing codebase\n"
            "Working (5s • esc to interrupt)\n"
            "? for shortcuts\n"
            "92% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.codex.tmux_client")
    def test_get_status_idle_despite_narrative_exploring(self, mock_tmux):
        # "exploring" in narrative text (without bullet prefix) should NOT block idle.
        mock_tmux.get_history.return_value = (
            "› Reply with READY\n"
            "• I was exploring the codebase and found the issue.\n"
            "  The fix is applied.\n"
            "›\n"
            "? for shortcuts\n"
            "95% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status in (TerminalStatus.IDLE, TerminalStatus.COMPLETED)

    def test_user_prefix_pattern_no_cross_line_match(self):
        # Standalone › followed by newline should NOT match USER_PREFIX_PATTERN.
        import re
        from cli_agent_orchestrator.providers.codex import USER_PREFIX_PATTERN

        # Should NOT match: standalone › with next line starting with digit
        text = "›\n100% context left"
        matches = list(re.finditer(USER_PREFIX_PATTERN, text, re.IGNORECASE | re.MULTILINE))
        assert len(matches) == 0, f"Unexpected match for standalone ›: {matches}"

        # Should match: › followed by text on the same line
        text2 = "› Reply with READY"
        matches2 = list(re.finditer(USER_PREFIX_PATTERN, text2, re.IGNORECASE | re.MULTILINE))
        assert len(matches2) == 1

        # Should match: › followed by tab and text on the same line
        text3 = "›\tReply with READY"
        matches3 = list(re.finditer(USER_PREFIX_PATTERN, text3, re.IGNORECASE | re.MULTILINE))
        assert len(matches3) == 1


class TestCodexProviderMessageExtraction:
    def test_extract_last_message_success(self):
        output = load_fixture("codex_completed_output.txt")

        provider = CodexProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        assert "Here's the fix" in message
        assert "All tests now pass." in message

    def test_extract_complex_message(self):
        output = load_fixture("codex_complex_response.txt")

        provider = CodexProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        assert "def add(a, b):" in message
        assert "Let me know" in message

    def test_extract_message_no_marker(self):
        output = "No assistant prefix here"

        provider = CodexProvider("test1234", "test-session", "window-0")

        with pytest.raises(ValueError, match="No Codex response found"):
            provider.extract_last_message_from_script(output)

    def test_extract_message_empty_response(self):
        output = "assistant:   \n\n❯ "

        provider = CodexProvider("test1234", "test-session", "window-0")

        with pytest.raises(ValueError, match="Empty Codex response"):
            provider.extract_last_message_from_script(output)

    def test_extract_message_v104_bullet_marker(self):
        output = "› Reply with READY2\n• READY2\n›\n100% context left\n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        assert message == "READY2"

    def test_extract_message_v104_multiline_bullet_response(self):
        output = "› Explain the fix\n• Here's the fix\nUpdate matcher for • and ›\n›\n100% context left\n"

        provider = CodexProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        assert message == "Here's the fix\nUpdate matcher for • and ›"

    def test_extract_message_with_ansi_control_sequences(self):
        output = (
            "› Return ANALYST_SUMMARY\n"
            "\x1b[1m\x1b[38;2;231;231;231;49m•\x1b[39m\x1b[49m "
            "*** ANALYST_SUMMARY ***\x1b[22;3H›Run /review on my current changes?\n"
            "Problem summary line\x1b[0m\n"
            "›\n"
            "100% context left\n"
        )

        provider = CodexProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        assert "*** ANALYST_SUMMARY ***" in message
        assert "Problem summary line" in message


class TestCodexProviderMisc:
    def test_get_idle_pattern_for_log(self):
        provider = CodexProvider("test1234", "test-session", "window-0")
        assert provider.get_idle_pattern_for_log() == "❯"

    def test_exit_cli(self):
        provider = CodexProvider("test1234", "test-session", "window-0")
        assert provider.exit_cli() == "/exit"

    def test_cleanup(self):
        provider = CodexProvider("test1234", "test-session", "window-0")
        provider._initialized = True
        provider.cleanup()
        assert provider._initialized is False

    def test_extract_last_message_without_trailing_prompt(self):
        output = "You do thing\nassistant: Hello\nSecond line\n"
        provider = CodexProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)
        assert message == "Hello\nSecond line"
