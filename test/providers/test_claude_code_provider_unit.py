"""Unit tests for Claude Code provider status detection."""

from unittest.mock import patch

import pytest

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.claude_code import ClaudeCodeProvider


class TestClaudeCodeGetStatus:
    """Tests for get_status() focusing on scrollback false-idle prevention."""

    def _make_provider(self):
        return ClaudeCodeProvider("test1234", "test-session", "window-0")

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_processing_spinner_detected(self, mock_tmux):
        """Active spinner in recent output -> PROCESSING."""
        mock_tmux.get_history.return_value = (
            "Some previous output\n"
            "❯ do something\n"
            "⏺ Working on it...\n"
            "✽ Cooking… (3s · ↓ 50 tokens · thinking)\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_idle_prompt_at_end(self, mock_tmux):
        """Idle prompt on last line -> IDLE."""
        mock_tmux.get_history.return_value = (
            "Some old output\n"
            "❯ \n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_idle_prompt_with_placeholder_text(self, mock_tmux):
        """Prompt with placeholder text (Claude Code v2.x) -> IDLE."""
        mock_tmux.get_history.return_value = (
            "Some old output\n"
            '❯ Try "how do I log an error?"\n'
            "────────────────────────────\n"
            "  ⏵⏵ bypass permissions on\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_completed_with_response_and_prompt(self, mock_tmux):
        """Response marker + idle prompt at end -> COMPLETED."""
        mock_tmux.get_history.return_value = (
            "❯ analyze this\n"
            "⏺ Here is my analysis...\n"
            "The code looks good.\n"
            "❯ \n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_completed_with_placeholder_and_status_bar(self, mock_tmux):
        """Response + prompt with placeholder + status bar -> COMPLETED."""
        mock_tmux.get_history.return_value = (
            "❯ analyze this\n"
            "⏺ Here is my analysis...\n"
            "The code looks good.\n"
            '❯ Try "how do I log an error?"\n'
            "────────────────────────────\n"
            "  ⏵⏵ bypass permissions on\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_stale_prompt_in_scrollback_while_processing(self, mock_tmux):
        """Old prompt in scrollback + agent running tools -> PROCESSING, not IDLE.

        This is the core regression test: when Claude Code runs tools (file edits,
        bash), the spinner disappears. An old prompt from earlier in history must NOT
        cause false idle detection.
        """
        # Simulate 20+ lines of tool output after an old prompt
        old_prompt = "❯ implement the feature\n"
        response_start = "⏺ I'll implement this now.\n"
        tool_output_lines = [f"  Writing file line {i}...\n" for i in range(20)]
        # No spinner, no prompt at end -- agent is running tools
        mock_tmux.get_history.return_value = (
            old_prompt + response_start + "".join(tool_output_lines)
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_stale_prompt_in_tail_range_while_processing(self, mock_tmux):
        """Old prompt mid-line in tool output -> PROCESSING (not at start of line)."""
        mock_tmux.get_history.return_value = (
            "⏺ Editing files...\n"
            "  Updated config with ❯ prefix handling\n"
            "  Fixed pattern matching\n"
            "  Running tests...\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_stale_prompt_on_non_last_line_with_response_after(self, mock_tmux):
        """Prompt followed by response marker -> PROCESSING (stale prompt).

        Even if prompt appears at start-of-line within the tail, a response
        marker after it means the agent sent a message and is processing.
        """
        mock_tmux.get_history.return_value = (
            "❯ implement the feature\n"
            "⏺ Working on it...\n"
            "  Wrote src/main.py\n"
            "  Wrote tests/test_main.py\n"
            "  Checking results...\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_no_output_returns_error(self, mock_tmux):
        """Empty output -> ERROR."""
        mock_tmux.get_history.return_value = ""
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_no_recognizable_state_returns_processing(self, mock_tmux):
        """Unrecognized output (tool running) -> PROCESSING, not ERROR."""
        mock_tmux.get_history.return_value = (
            "Reading file src/main.py\n"
            "Analyzing dependencies\n"
            "Checking imports\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_error_pattern_detected(self, mock_tmux):
        """Error pattern in recent output -> ERROR."""
        mock_tmux.get_history.return_value = (
            "⏺ Running command...\n"
            "Traceback (most recent call last):\n"
            '  File "main.py", line 1\n'
            "Error: something went wrong\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_error_in_scrollback_but_idle_prompt_wins(self, mock_tmux):
        """Error text in output + idle prompt after -> COMPLETED (prompt wins)."""
        mock_tmux.get_history.return_value = (
            "⏺ Running command...\n"
            "Error: something failed earlier\n"
            "❯ \n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_waiting_user_answer(self, mock_tmux):
        """Selection prompt -> WAITING_USER_ANSWER."""
        mock_tmux.get_history.return_value = (
            "⏺ Which option?\n"
            "❯ 1. Option A\n"
            "  2. Option B\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_idle_prompt_with_ansi_codes(self, mock_tmux):
        """Idle prompt wrapped in ANSI color codes -> IDLE (codes stripped)."""
        mock_tmux.get_history.return_value = (
            "Some output\n"
            "\x1b[38;2;130;170;255m❯\x1b[0m \n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_idle_prompt_with_cursor_control_sequences_below(self, mock_tmux):
        """Prompt followed by cursor control lines -> IDLE (ghost lines stripped)."""
        mock_tmux.get_history.return_value = (
            "Some output\n"
            "\x1b[38;2;130;170;255m❯\x1b[0m \n"
            "\x1b[?25h\n"
            "\x1b[K\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_trailing_blanks_stripped(self, mock_tmux):
        """Trailing blank lines should not prevent detection."""
        mock_tmux.get_history.return_value = (
            "⏺ Done.\n"
            "❯ \n"
            "\n"
            "\n"
            "\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.COMPLETED

    # ── Permission prompt detection tests ──────────────────────────────────

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_permission_prompt_command(self, mock_tmux):
        """Active 'Would you like to run' permission prompt -> WAITING_USER_ANSWER."""
        mock_tmux.get_history.return_value = (
            "⏺ I need to run a command outside the sandbox.\n"
            "\n"
            "Would you like to run the following command?\n"
            "Reason: Do you want me to run the frontend production build outside sandbox\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_permission_prompt_sandbox_escape(self, mock_tmux):
        """Sandbox escape confirmation -> WAITING_USER_ANSWER."""
        mock_tmux.get_history.return_value = (
            "⏺ Running build.\n"
            "\n"
            "Do you want to run the build outside the sandbox?\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_stale_permission_prompt_with_idle_after(self, mock_tmux):
        """Permission prompt followed by idle prompt -> not WAITING_USER_ANSWER."""
        mock_tmux.get_history.return_value = (
            "⏺ Running build...\n"
            "Would you like to run the following command?\n"
            "Reason: build outside sandbox\n"
            "⏺ Build completed successfully.\n"
            "❯ \n"
        )
        provider = self._make_provider()
        # Stale permission prompt — should be COMPLETED (response + idle prompt)
        assert provider.get_status() == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_newer_permission_prompt_detected_after_stale_different_pattern(self, mock_tmux):
        """Stale prompt of pattern A + active prompt of pattern B -> WAITING_USER_ANSWER.

        Regression test: ensures the latest match across all patterns is used,
        not just the first matched pattern.
        """
        mock_tmux.get_history.return_value = (
            "Would you like to run the following command?\n"  # pattern A (stale)
            "Reason: earlier command\n"
            "❯ \n"  # idle prompt after pattern A -> stale
            "⏺ Now running another task.\n"
            "Allow the build tool to run this\n"  # pattern C (active, appears later)
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_permission_prompt_with_spinner_is_processing(self, mock_tmux):
        """Permission prompt text in scrollback + active spinner -> PROCESSING."""
        mock_tmux.get_history.return_value = (
            "Would you like to run the following command?\n"
            "Reason: build\n"
            "✽ Cooking… (3s · ↓ 50 tokens · thinking)\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.claude_code.tmux_client")
    def test_real_claude_code_v2_startup_output(self, mock_tmux):
        """Realistic Claude Code v2.x startup output -> IDLE."""
        mock_tmux.get_history.return_value = (
            "% cd /some/dir && env -u CLAUDECODE claude --dangerously-skip-permissions\n"
            "\n"
            "    ✻\n"
            "    |\n"
            "   ▟█▙     Claude Code v2.1.50\n"
            " ▐▛███▜▌   Opus 4.6 · Claude Max\n"
            "▝▜█████▛▘  ~/project/test\n"
            "  ▘▘ ▝▝\n"
            "\n"
            "────────────────────────────────────────────────────────────────────\n"
            '❯ Try "how do I log an error?"\n'
            "────────────────────────────────────────────────────────────────────\n"
            "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
        )
        provider = self._make_provider()
        assert provider.get_status() == TerminalStatus.IDLE
