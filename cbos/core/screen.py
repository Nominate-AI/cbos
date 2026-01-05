"""GNU Screen session manager for Claude Code"""

import re
import subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from .models import SessionState
from .logging import get_logger

logger = get_logger("screen")


@dataclass
class ScreenSession:
    """Raw screen session info from `screen -ls`"""

    pid: int
    name: str
    screen_id: str  # "pid.name"
    attached: bool
    timestamp: Optional[str] = None


class ScreenManager:
    """Manages GNU Screen sessions running Claude Code"""

    # Patterns for detecting Claude Code state from buffer
    WAITING_PATTERNS = [
        r"^>\s*$",  # Empty prompt
        r"^> $",  # Prompt with space
        r">\u2588$",  # Prompt with cursor block
    ]

    # Patterns for Claude Code question/choice dialogs (also WAITING state)
    QUESTION_DIALOG_PATTERNS = [
        r"Esc to cancel",  # Choice dialog footer
        r"^\s*[❯o]\s*\d+\.\s+",  # Selection cursor on numbered option (❯ or 'o' in hardcopy)
        r"^\s*\d+\.\s+(Yes|No|Skip|Cancel|Continue|Allow)",  # Numbered Yes/No options
        r"Do you want to\s",  # Common question pattern
        r"Would you like to\s",  # Common question pattern
        r"Should I\s",  # Common question pattern
        r"^\s*Type here to tell Claude",  # Custom input option
    ]

    THINKING_PATTERNS = [
        r"[●◐◑◒◓]",  # Spinner characters
        r"Thinking",
    ]

    WORKING_PATTERNS = [
        r"^[✓✗⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]",  # Tool status indicators at line start
        r"^\s*(Bash|Read|Write|Edit|Grep|Glob|Task|WebFetch)\(",  # Active tool calls
        r"Running in the background",
    ]

    ERROR_PATTERNS = [
        r"(?:^|\s)Error:",      # Error: at start or after whitespace
        r"(?:^|\s)error:",      # error: at start or after whitespace
        r"(?:^|\s)FAILED",      # FAILED at start or after whitespace
        r"(?:^|\s)Exception:",  # Exception: at start or after whitespace
    ]

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or Path.home() / "claude_logs"
        self.log_dir.mkdir(exist_ok=True)

    def list_sessions(self) -> list[ScreenSession]:
        """List all screen sessions"""
        logger.debug("Listing screen sessions")
        result = subprocess.run(
            ["screen", "-ls"], capture_output=True, text=True
        )

        sessions = []
        # Parse: 900379.AUTH (01/01/2026 09:00:39 PM) (Attached)
        pattern = r"(\d+)\.(\S+)\s+\(([^)]+)\)\s+\((Attached|Detached)\)"

        for match in re.finditer(pattern, result.stdout):
            pid = int(match.group(1))
            name = match.group(2)
            timestamp = match.group(3)
            attached = match.group(4) == "Attached"

            sessions.append(
                ScreenSession(
                    pid=pid,
                    name=name,
                    screen_id=f"{pid}.{name}",
                    attached=attached,
                    timestamp=timestamp,
                )
            )

        logger.debug(f"Found {len(sessions)} sessions: {[s.name for s in sessions]}")
        return sessions

    def get_session(self, slug: str) -> Optional[ScreenSession]:
        """Get a specific session by slug/name"""
        for session in self.list_sessions():
            if session.name == slug:
                return session
        return None

    def launch(
        self,
        slug: str,
        path: str,
        resume: bool = False,
        no_color: bool = True,
        streaming: bool = True,
    ) -> ScreenSession:
        """
        Launch a new Claude Code session in screen.

        Args:
            slug: Session name (e.g., "AUTH", "INTEL")
            path: Working directory for Claude Code
            resume: Whether to pass --resume to claude
            no_color: Whether to disable ANSI colors
            streaming: Whether to wrap in script -f for streaming (default: True)
        """
        from .config import get_config

        # Check if session already exists
        existing = self.get_session(slug)
        if existing:
            raise ValueError(f"Session '{slug}' already exists")

        logfile = self.log_dir / f"{slug}.log"

        # Build the claude command
        claude_cmd = "claude"
        if resume:
            claude_cmd += " --resume"

        # Environment setup
        env_setup = ""
        if no_color:
            env_setup = "NO_COLOR=1 "

        if streaming:
            # Streaming mode: wrap claude in script -f for real-time capture
            config = get_config()
            stream_dir = config.stream.stream_dir
            stream_dir.mkdir(parents=True, exist_ok=True)

            typescript_file = stream_dir / f"{slug}.typescript"
            timing_file = stream_dir / f"{slug}.timing"

            # script -f flushes output immediately
            # -c runs a command instead of shell
            script_cmd = (
                f"script -f --timing={timing_file} {typescript_file} "
                f"-c 'cd \"{path}\" && {env_setup}{claude_cmd}'"
            )
            bash_cmd = script_cmd
            logger.info(f"Launching streaming session: {slug} -> {typescript_file}")
        else:
            # Legacy mode: direct command
            bash_cmd = f"cd '{path}' && {env_setup}{claude_cmd}"
            logger.info(f"Launching legacy session: {slug}")

        cmd = [
            "screen",
            "-dmS",
            slug,
            "-L",
            "-Logfile",
            str(logfile),
            "bash",
            "-c",
            bash_cmd,
        ]

        subprocess.run(cmd, check=True)

        # Retrieve the new session
        session = self.get_session(slug)
        if not session:
            raise RuntimeError(f"Failed to find launched session '{slug}'")

        return session

    def kill(self, slug: str) -> bool:
        """Kill a screen session"""
        result = subprocess.run(
            ["screen", "-S", slug, "-X", "quit"], capture_output=True
        )
        return result.returncode == 0

    def capture_buffer(self, slug: str, tail_lines: int = 100) -> str:
        """
        Capture the scrollback buffer from a session.

        Args:
            slug: Session name
            tail_lines: Number of lines to return from the end

        Returns:
            Cleaned buffer content (ANSI codes stripped)
        """
        tmp = Path(f"/tmp/cbos_{slug}.txt")
        logger.debug(f"[{slug}] Capturing buffer to {tmp}")

        result = subprocess.run(
            ["screen", "-S", slug, "-X", "hardcopy", "-h", str(tmp)],
            capture_output=True,
        )

        if result.returncode != 0:
            logger.error(f"[{slug}] hardcopy failed: rc={result.returncode}")
            raise RuntimeError(f"Failed to capture buffer for '{slug}'")

        if not tmp.exists():
            logger.warning(f"[{slug}] Buffer file not found: {tmp}")
            return ""

        content = tmp.read_text(errors="replace")
        raw_len = len(content)

        # Strip ANSI escape codes
        content = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", content)
        # Strip other control characters but keep newlines
        content = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", content)

        # Return last N lines
        lines = content.strip().split("\n")

        # Filter out empty lines from the top (screen buffer padding)
        while lines and not lines[0].strip():
            lines.pop(0)

        result_lines = lines[-tail_lines:]
        logger.debug(f"[{slug}] Buffer: {raw_len} bytes -> {len(result_lines)} lines")

        return "\n".join(result_lines)

    def send_input(self, slug: str, text: str) -> bool:
        """
        Send keystrokes to a session.

        Args:
            slug: Session name
            text: Text to send (carriage return will be sent after to submit)

        Returns:
            True if successful
        """
        import time

        # The 'stuff' command sends literal characters
        # We need to escape single quotes for the shell
        escaped = text.replace("\\", "\\\\").replace("'", "'\\''")

        # Send text first
        result = subprocess.run(
            ["screen", "-S", slug, "-X", "stuff", escaped],
            capture_output=True,
        )
        if result.returncode != 0:
            return False

        # Small delay to let TUI process text
        time.sleep(0.1)

        # Send carriage return to submit (Enter key sends CR, not LF)
        # Claude Code's TUI expects CR to submit input
        result = subprocess.run(
            ["screen", "-S", slug, "-X", "stuff", "\r"],
            capture_output=True,
        )
        return result.returncode == 0

    def send_interrupt(self, slug: str) -> bool:
        """Send Ctrl+C to a session"""
        result = subprocess.run(
            ["screen", "-S", slug, "-X", "stuff", "\x03"],
            capture_output=True,
        )
        return result.returncode == 0

    def detect_state(self, buffer: str, slug: str = "") -> tuple[SessionState, Optional[str]]:
        """
        Detect Claude Code state from buffer content.

        Args:
            buffer: The captured buffer content
            slug: Session identifier for logging

        Returns:
            Tuple of (state, last_question_if_waiting)
        """
        log_prefix = f"[{slug}] " if slug else ""

        if not buffer.strip():
            logger.debug(f"{log_prefix}Empty buffer -> UNKNOWN")
            return SessionState.UNKNOWN, None

        lines = buffer.strip().split("\n")
        last_line = lines[-1] if lines else ""
        tail = "\n".join(lines[-15:])  # Last 15 lines for pattern matching

        # Log the last line for debugging (truncated)
        last_line_preview = last_line[:60].replace('\n', '\\n') if last_line else "(empty)"
        logger.debug(f"{log_prefix}Last line: {repr(last_line_preview)}")

        # Check for waiting state (prompt visible)
        # Claude Code shows status bar lines below the prompt, so check last 5 lines
        recent_lines = lines[-5:] if len(lines) >= 5 else lines
        for line in recent_lines:
            line_stripped = line.strip()
            # Check for prompt patterns
            for pattern in self.WAITING_PATTERNS:
                if re.search(pattern, line_stripped):
                    question = self._extract_last_question(lines)
                    logger.debug(f"{log_prefix}Pattern '{pattern}' matched in recent lines -> WAITING")
                    return SessionState.WAITING, question

            # Also check if line is just ">" with possible cursor block or special chars
            # 0xa0 = non-breaking space, \u2588 = █ cursor block, \ufffd = replacement char
            if line_stripped in (">", "> ", ">\u2588", ">█", ">\xa0", "> \xa0", ">\ufffd", "> \ufffd"):
                question = self._extract_last_question(lines)
                logger.debug(f"{log_prefix}Prompt char detected in recent lines -> WAITING")
                return SessionState.WAITING, question
            # Also check if line starts with ">" and rest is whitespace or special chars
            if line_stripped.startswith(">"):
                # Remove non-breaking space, replacement char, and other common terminal artifacts
                rest = line_stripped[1:].replace("\xa0", "").replace("\ufffd", "").strip()
                if len(rest) == 0:
                    question = self._extract_last_question(lines)
                    logger.debug(f"{log_prefix}Prompt '>' with special chars detected -> WAITING")
                    return SessionState.WAITING, question

        # Check for question/choice dialog (also WAITING state)
        # Check last 10 lines for dialog patterns
        dialog_check_lines = lines[-10:] if len(lines) >= 10 else lines
        for line in dialog_check_lines:
            for pattern in self.QUESTION_DIALOG_PATTERNS:
                if re.search(pattern, line):
                    question = self._extract_question_dialog(lines)
                    logger.debug(f"{log_prefix}Question dialog pattern '{pattern}' matched -> WAITING")
                    return SessionState.WAITING, question

        # Check for thinking state
        for pattern in self.THINKING_PATTERNS:
            if re.search(pattern, tail):
                logger.debug(f"{log_prefix}Pattern '{pattern}' matched -> THINKING")
                return SessionState.THINKING, None

        # Check for working state (tool execution) - check each recent line
        recent_lines = lines[-10:]
        for line in recent_lines:
            for pattern in self.WORKING_PATTERNS:
                if re.search(pattern, line):
                    logger.debug(f"{log_prefix}Pattern '{pattern}' matched -> WORKING")
                    return SessionState.WORKING, None

        # Check for error state - only in last 5 lines to avoid false positives from old output
        error_check_lines = lines[-5:] if len(lines) >= 5 else lines
        for line in error_check_lines:
            for pattern in self.ERROR_PATTERNS:
                if re.search(pattern, line):
                    logger.debug(f"{log_prefix}Pattern '{pattern}' matched in recent lines -> ERROR")
                    return SessionState.ERROR, None

        # Default to idle - log more detail to help debug
        last_chars = repr(last_line[-20:]) if len(last_line) > 20 else repr(last_line)
        logger.debug(f"{log_prefix}No patterns matched -> IDLE (last_chars={last_chars})")
        return SessionState.IDLE, None

    def _extract_last_question(
        self, lines: list[str], max_lines: int = 10
    ) -> Optional[str]:
        """
        Extract the last question/output Claude showed before the prompt.

        Looks backwards from the prompt to find Claude's message.
        """
        question_lines = []

        # Start from second-to-last line (skip the prompt)
        for line in reversed(lines[:-1]):
            stripped = line.strip()

            # Stop if we hit a previous user input (starts with >)
            if stripped.startswith(">") and not stripped.startswith("> "):
                break

            # Stop if we hit a tool result marker
            if stripped.startswith("Agent pid") or stripped.startswith("Identity added"):
                continue  # Skip these noise lines

            if stripped:
                question_lines.insert(0, stripped)

            if len(question_lines) >= max_lines:
                break

        return "\n".join(question_lines) if question_lines else None

    def _extract_question_dialog(
        self, lines: list[str], max_lines: int = 15
    ) -> Optional[str]:
        """
        Extract the question from a Claude Code choice dialog.

        Looks for the question text before the numbered options.
        """
        # Find the question line (ends with ?)
        for i, line in enumerate(reversed(lines[-max_lines:])):
            stripped = line.strip()
            # Look for question ending with ?
            if stripped.endswith("?"):
                return stripped
            # Also check for "Do you want to" pattern without ?
            if re.search(r"(Do you want to|Would you like to|Should I)\s", stripped):
                return stripped

        # Fallback: return the first non-empty line that's not an option
        for line in lines[-max_lines:]:
            stripped = line.strip()
            if stripped and not re.match(r"^\s*\d+\.", stripped) and "Esc to" not in stripped:
                # Skip lines that look like options or separators
                if not re.match(r"^[Lo\s❯]+$", stripped):  # L=separator, o=selection
                    return stripped

        return None

    def get_log_path(self, slug: str) -> Path:
        """Get the log file path for a session"""
        return self.log_dir / f"{slug}.log"

    def attach_command(self, slug: str) -> str:
        """Get the command to attach to a session"""
        return f"screen -r {slug}"
