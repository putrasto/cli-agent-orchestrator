"""Codex CLI provider implementation."""

import logging
import re
from typing import Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider
from cli_agent_orchestrator.utils.terminal import wait_for_shell, wait_until_status

logger = logging.getLogger(__name__)

# Regex patterns for Codex output analysis
ANSI_CODE_PATTERN = r"\x1b\[[0-?]*[ -/]*[@-~]"
OSC_PATTERN = r"\x1b\][^\x07]*(?:\x07|\x1b\\)"
IDLE_PROMPT_PATTERN = r"(?:❯|›|codex>)"
# Match the prompt only if it appears at the end of the captured output.
# Allows trailing text on the same line (e.g., "What would you like to do next?")
IDLE_PROMPT_AT_END_PATTERN = rf"(?:^\s*{IDLE_PROMPT_PATTERN}\s*)\s*\Z"
IDLE_PROMPT_LINE_PATTERN = rf"^\s*{IDLE_PROMPT_PATTERN}\s*$"
IDLE_PROMPT_PATTERN_LOG = r"❯"
# Codex markers vary by version:
# - legacy: "assistant:", "You ..."
# - v0.104+: "• ..." (assistant), "› ..." (user)
ASSISTANT_PREFIX_PATTERN = r"^(?:(?:assistant|codex|agent)\s*:|•\s+)"
USER_PREFIX_PATTERN = r"^(?:You\b|›\s+\S)"
CONTEXT_FOOTER_PATTERN = r"^\s*\d+%\s+context left\s*$"

PROCESSING_PATTERN = r"\b(thinking|working|running|executing|processing|analyzing)\b"
WAITING_PROMPT_PATTERN = r"^(?:Approve|Allow)\b.*\b(?:y/n|yes/no|yes|no)\b"
ERROR_PATTERN = r"^(?:Error:|ERROR:|Traceback \(most recent call last\):|panic:)"


class CodexProvider(BaseProvider):
    """Provider for Codex CLI tool integration."""

    def __init__(
        self,
        terminal_id: str,
        session_name: str,
        window_name: str,
        agent_profile: Optional[str] = None,
    ):
        super().__init__(terminal_id, session_name, window_name)
        self._initialized = False
        self._agent_profile = agent_profile

    @staticmethod
    def _clean_terminal_output(output: str) -> str:
        """Strip control sequences and normalize line endings for parsing."""
        output = re.sub(OSC_PATTERN, "", output)
        output = re.sub(ANSI_CODE_PATTERN, "", output)
        return output.replace("\r", "\n")

    def initialize(self) -> bool:
        """Initialize Codex provider by starting codex command."""
        if not wait_for_shell(tmux_client, self.session_name, self.window_name, timeout=10.0):
            raise TimeoutError("Shell initialization timed out after 10 seconds")

        tmux_client.send_keys(self.session_name, self.window_name, "codex")

        if not wait_until_status(self, TerminalStatus.IDLE, timeout=60.0, polling_interval=1.0):
            raise TimeoutError("Codex initialization timed out after 60 seconds")

        self._initialized = True
        return True

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Get Codex status by analyzing terminal output."""
        output = tmux_client.get_history(self.session_name, self.window_name, tail_lines=tail_lines)

        if not output:
            return TerminalStatus.ERROR

        clean_output = self._clean_terminal_output(output)
        tail_output = "\n".join(clean_output.splitlines()[-25:])
        tail_output_lower = tail_output.lower()

        last_user = None
        for match in re.finditer(USER_PREFIX_PATTERN, clean_output, re.IGNORECASE | re.MULTILINE):
            last_user = match

        output_after_last_user = clean_output[last_user.start() :] if last_user else clean_output
        assistant_after_last_user = bool(
            last_user
            and re.search(
                ASSISTANT_PREFIX_PATTERN,
                output_after_last_user,
                re.IGNORECASE | re.MULTILINE,
            )
        )

        has_idle_prompt_at_end = bool(
            re.search(IDLE_PROMPT_AT_END_PATTERN, clean_output, re.IGNORECASE | re.MULTILINE)
        )
        # Codex v0.104+ prompt detection:
        # The UI can show a "›" prompt with footer text like "100% context left",
        # which means the prompt may not appear at the end of captured output.
        has_v104_idle_prompt = (
            "context left" in tail_output_lower
            or bool(re.search(r"^\s*›\s*$", tail_output, re.IGNORECASE | re.MULTILINE))
        )

        # Only treat ERROR/WAITING prompts as actionable if they appear after the last user message
        # and are not part of an assistant response.
        if last_user is not None:
            if not assistant_after_last_user:
                if re.search(
                    WAITING_PROMPT_PATTERN,
                    output_after_last_user,
                    re.IGNORECASE | re.MULTILINE,
                ):
                    return TerminalStatus.WAITING_USER_ANSWER
                if re.search(
                    ERROR_PATTERN,
                    output_after_last_user,
                    re.IGNORECASE | re.MULTILINE,
                ):
                    return TerminalStatus.ERROR
        else:
            if re.search(WAITING_PROMPT_PATTERN, tail_output, re.IGNORECASE | re.MULTILINE):
                return TerminalStatus.WAITING_USER_ANSWER
            if re.search(ERROR_PATTERN, tail_output, re.IGNORECASE | re.MULTILINE):
                return TerminalStatus.ERROR
        if has_idle_prompt_at_end or has_v104_idle_prompt:
            # Consider COMPLETED only if we see an assistant marker after the last user message.
            if last_user is not None:
                if re.search(
                    ASSISTANT_PREFIX_PATTERN,
                    clean_output[last_user.start() :],
                    re.IGNORECASE | re.MULTILINE,
                ):
                    return TerminalStatus.COMPLETED

                return TerminalStatus.IDLE

            return TerminalStatus.IDLE

        # If we're not at an idle prompt and we don't see explicit errors/permission prompts,
        # assume the CLI is still producing output.
        return TerminalStatus.PROCESSING

    def get_idle_pattern_for_log(self) -> str:
        """Return Codex IDLE prompt pattern for log files."""
        return IDLE_PROMPT_PATTERN_LOG

    def extract_last_message_from_script(self, script_output: str) -> str:
        """Extract Codex's final response message from legacy or v0.104+ markers."""
        clean_output = self._clean_terminal_output(script_output)

        matches = list(
            re.finditer(ASSISTANT_PREFIX_PATTERN, clean_output, re.IGNORECASE | re.MULTILINE)
        )

        if not matches:
            raise ValueError("No Codex response found - no assistant marker detected")

        last_match = matches[-1]
        start_pos = last_match.end()

        output_after_last_assistant = clean_output[start_pos:]
        lines = output_after_last_assistant.splitlines()
        message_lines = []
        for idx, line in enumerate(lines):
            # Only treat prompt/user/footer lines as boundaries after we've started
            # collecting assistant content.
            if idx > 0 and (
                re.match(USER_PREFIX_PATTERN, line, re.IGNORECASE)
                or re.match(IDLE_PROMPT_LINE_PATTERN, line, re.IGNORECASE)
                or re.match(CONTEXT_FOOTER_PATTERN, line, re.IGNORECASE)
            ):
                break
            message_lines.append(line)

        final_answer = "\n".join(message_lines).strip()

        if not final_answer:
            raise ValueError("Empty Codex response - no content found")

        return final_answer

    def exit_cli(self) -> str:
        """Get the command to exit Codex CLI."""
        return "/exit"

    def cleanup(self) -> None:
        """Clean up Codex CLI provider."""
        self._initialized = False
