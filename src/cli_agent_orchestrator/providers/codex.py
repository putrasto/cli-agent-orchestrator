"""Codex CLI provider implementation."""

import logging
import os
import re
from typing import Any, Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider
from cli_agent_orchestrator.utils.terminal import wait_for_shell, wait_until_status

logger = logging.getLogger(__name__)

# Regex patterns for Codex output analysis
ANSI_CODE_PATTERN = r"\x1b\[[0-?]*[ -/]*[@-~]"
OSC_PATTERN = r"\x1b\][^\x07]*(?:\x07|\x1b\\)"
IDLE_PROMPT_PATTERN = r"(?:❯|›|codex>)"
# Match prompt if it appears at the end of captured output.
# Codex may render a hint line like: "› ... for shortcuts"
IDLE_PROMPT_AT_END_PATTERN = (
    rf"(?:^|\n)\s*(?:{IDLE_PROMPT_PATTERN}\s*|›\s+.*for shortcuts.*)\s*\Z"
)
IDLE_PROMPT_LINE_PATTERN = rf"^\s*{IDLE_PROMPT_PATTERN}\s*$"
PROMPT_HINT_LINE_PATTERN = r"^\s*›\s+.*for shortcuts.*$"
IDLE_PROMPT_PATTERN_LOG = r"❯"
# Codex markers vary by version:
# - legacy: "assistant:", "You ..."
# - v0.104+: "• ..." (assistant), "› ..." (user)
ASSISTANT_PREFIX_PATTERN = r"^\s*(?:(?:assistant|codex|agent)\s*:|•\s+)"
USER_PREFIX_PATTERN = r"^\s*(?:You\b|›\s+\S)"
CONTEXT_FOOTER_PATTERN = r"^\s*\d+%\s+context left\s*$"

PROCESSING_PATTERN = r"\b(thinking|working|running|executing|processing|analyzing)\b"
WAITING_PROMPT_PATTERN = r"^(?:Approve|Allow)\b.*\b(?:y/n|yes/no|yes|no)\b"
ERROR_PATTERN = r"^(?:Error:|ERROR:|Traceback \(most recent call last\):|panic:)"


def _get_float_env(name: str, default: float) -> float:
    """Parse float env var with safe fallback."""
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _is_truthy_env(name: str) -> bool:
    """Parse boolean env var using common truthy values."""
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


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

    @staticmethod
    def _tail_excerpt(text: str, max_lines: int = 8, max_chars_per_line: int = 160) -> str:
        """Build a compact single-line tail excerpt for logs."""
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""

        tail_lines = lines[-max_lines:]
        clipped_lines = []
        for line in tail_lines:
            if len(line) > max_chars_per_line:
                clipped_lines.append(f"{line[:max_chars_per_line]}...")
            else:
                clipped_lines.append(line)

        return " | ".join(clipped_lines)

    def _analyze_clean_output(self, clean_output: str) -> dict[str, Any]:
        """Analyze normalized output and return status with matching signals."""
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
        has_v104_idle_prompt = (
            "context left" in tail_output_lower
            or bool(re.search(r"^\s*›\s*$", tail_output, re.IGNORECASE | re.MULTILINE))
            or bool(re.search(PROMPT_HINT_LINE_PATTERN, tail_output, re.IGNORECASE | re.MULTILINE))
        )

        waiting_after_last_user = bool(
            last_user is not None
            and not assistant_after_last_user
            and re.search(
                WAITING_PROMPT_PATTERN,
                output_after_last_user,
                re.IGNORECASE | re.MULTILINE,
            )
        )
        error_after_last_user = bool(
            last_user is not None
            and not assistant_after_last_user
            and re.search(
                ERROR_PATTERN,
                output_after_last_user,
                re.IGNORECASE | re.MULTILINE,
            )
        )
        waiting_no_user = bool(
            last_user is None
            and re.search(WAITING_PROMPT_PATTERN, tail_output, re.IGNORECASE | re.MULTILINE)
        )
        error_no_user = bool(
            last_user is None and re.search(ERROR_PATTERN, tail_output, re.IGNORECASE | re.MULTILINE)
        )

        status = TerminalStatus.PROCESSING
        reason = "default_processing"

        if waiting_after_last_user or waiting_no_user:
            status = TerminalStatus.WAITING_USER_ANSWER
            reason = "waiting_prompt_detected"
        elif error_after_last_user or error_no_user:
            status = TerminalStatus.ERROR
            reason = "error_pattern_detected"
        elif has_idle_prompt_at_end or has_v104_idle_prompt:
            if last_user is not None and assistant_after_last_user:
                status = TerminalStatus.COMPLETED
                reason = "idle_with_assistant_after_last_user"
            else:
                status = TerminalStatus.IDLE
                reason = "idle_prompt_detected"

        return {
            "status": status,
            "reason": reason,
            "has_idle_prompt_at_end": has_idle_prompt_at_end,
            "has_v104_idle_prompt": has_v104_idle_prompt,
            "has_last_user": last_user is not None,
            "assistant_after_last_user": assistant_after_last_user,
            "waiting_after_last_user": waiting_after_last_user,
            "error_after_last_user": error_after_last_user,
            "waiting_no_user": waiting_no_user,
            "error_no_user": error_no_user,
            "tail_excerpt": self._tail_excerpt(tail_output),
        }

    def get_status_debug_snapshot(self, tail_lines: Optional[int] = None) -> dict[str, Any]:
        """Return status plus parsing signals for troubleshooting."""
        output = tmux_client.get_history(self.session_name, self.window_name, tail_lines=tail_lines)
        if not output:
            return {
                "status": TerminalStatus.ERROR,
                "reason": "empty_output",
                "has_idle_prompt_at_end": False,
                "has_v104_idle_prompt": False,
                "has_last_user": False,
                "assistant_after_last_user": False,
                "waiting_after_last_user": False,
                "error_after_last_user": False,
                "waiting_no_user": False,
                "error_no_user": False,
                "tail_excerpt": "",
            }

        clean_output = self._clean_terminal_output(output)
        return self._analyze_clean_output(clean_output)

    def initialize(self) -> bool:
        """Initialize Codex provider by starting codex command."""
        init_timeout_seconds = _get_float_env("CAO_CODEX_INIT_TIMEOUT_SECONDS", 180.0)
        debug_init = _is_truthy_env("CAO_DEBUG_CODEX_INIT")

        if not wait_for_shell(tmux_client, self.session_name, self.window_name, timeout=10.0):
            raise TimeoutError("Shell initialization timed out after 10 seconds")

        tmux_client.send_keys(self.session_name, self.window_name, "codex")

        def _on_status_poll(
            _provider: BaseProvider,
            current_status: TerminalStatus,
            poll_count: int,
            elapsed_seconds: float,
        ) -> None:
            if not debug_init:
                return

            snapshot = self.get_status_debug_snapshot(tail_lines=200)
            logger.info(
                "Codex init debug poll=%s elapsed=%.1fs status=%s reason=%s "
                "idle_end=%s idle_v104=%s last_user=%s assistant_after_user=%s "
                "waiting_after_user=%s error_after_user=%s waiting_no_user=%s error_no_user=%s "
                'tail="%s"',
                poll_count,
                elapsed_seconds,
                current_status,
                snapshot["reason"],
                snapshot["has_idle_prompt_at_end"],
                snapshot["has_v104_idle_prompt"],
                snapshot["has_last_user"],
                snapshot["assistant_after_last_user"],
                snapshot["waiting_after_last_user"],
                snapshot["error_after_last_user"],
                snapshot["waiting_no_user"],
                snapshot["error_no_user"],
                snapshot["tail_excerpt"],
            )

        if not wait_until_status(
            self,
            TerminalStatus.IDLE,
            timeout=init_timeout_seconds,
            polling_interval=1.0,
            on_poll=_on_status_poll if debug_init else None,
        ):
            raise TimeoutError(
                f"Codex initialization timed out after {int(init_timeout_seconds)} seconds"
            )

        self._initialized = True
        return True

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Get Codex status by analyzing terminal output."""
        output = tmux_client.get_history(self.session_name, self.window_name, tail_lines=tail_lines)

        if not output:
            return TerminalStatus.ERROR

        clean_output = self._clean_terminal_output(output)
        status_snapshot = self._analyze_clean_output(clean_output)
        return status_snapshot["status"]

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
