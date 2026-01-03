"""GNU Screen session manager for Claude Code"""

import re
import subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from .models import SessionState


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
        r"Error:",
        r"error:",
        r"FAILED",
        r"Exception:",
    ]

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or Path.home() / "claude_logs"
        self.log_dir.mkdir(exist_ok=True)

    def list_sessions(self) -> list[ScreenSession]:
        """List all screen sessions"""
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
    ) -> ScreenSession:
        """
        Launch a new Claude Code session in screen.

        Args:
            slug: Session name (e.g., "AUTH", "INTEL")
            path: Working directory for Claude Code
            resume: Whether to pass --resume to claude
            no_color: Whether to disable ANSI colors
        """
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

        # Full command
        bash_cmd = f"cd '{path}' && {env_setup}{claude_cmd}"

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

        result = subprocess.run(
            ["screen", "-S", slug, "-X", "hardcopy", "-h", str(tmp)],
            capture_output=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to capture buffer for '{slug}'")

        if not tmp.exists():
            return ""

        content = tmp.read_text(errors="replace")

        # Strip ANSI escape codes
        content = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", content)
        # Strip other control characters but keep newlines
        content = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", content)

        # Return last N lines
        lines = content.strip().split("\n")

        # Filter out empty lines from the top (screen buffer padding)
        while lines and not lines[0].strip():
            lines.pop(0)

        return "\n".join(lines[-tail_lines:])

    def send_input(self, slug: str, text: str) -> bool:
        """
        Send keystrokes to a session.

        Args:
            slug: Session name
            text: Text to send (newline will be appended)

        Returns:
            True if successful
        """
        # The 'stuff' command sends literal characters
        # We need to escape single quotes for the shell
        escaped = text.replace("\\", "\\\\").replace("'", "'\\''")

        result = subprocess.run(
            ["screen", "-S", slug, "-X", "stuff", f"{escaped}\n"],
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

    def detect_state(self, buffer: str) -> tuple[SessionState, Optional[str]]:
        """
        Detect Claude Code state from buffer content.

        Args:
            buffer: The captured buffer content

        Returns:
            Tuple of (state, last_question_if_waiting)
        """
        if not buffer.strip():
            return SessionState.UNKNOWN, None

        lines = buffer.strip().split("\n")
        last_line = lines[-1] if lines else ""
        tail = "\n".join(lines[-15:])  # Last 15 lines for pattern matching

        # Check for waiting state (prompt visible)
        for pattern in self.WAITING_PATTERNS:
            if re.search(pattern, last_line):
                question = self._extract_last_question(lines)
                return SessionState.WAITING, question

        # Also check if last line is just ">" with possible whitespace
        if last_line.strip() in (">", "> ", ">\u2588"):
            question = self._extract_last_question(lines)
            return SessionState.WAITING, question

        # Check for thinking state
        for pattern in self.THINKING_PATTERNS:
            if re.search(pattern, tail):
                return SessionState.THINKING, None

        # Check for working state (tool execution) - check each recent line
        recent_lines = lines[-10:]
        for line in recent_lines:
            for pattern in self.WORKING_PATTERNS:
                if re.search(pattern, line):
                    return SessionState.WORKING, None

        # Check for error state
        for pattern in self.ERROR_PATTERNS:
            if re.search(pattern, tail):
                return SessionState.ERROR, None

        # Default to idle
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

    def get_log_path(self, slug: str) -> Path:
        """Get the log file path for a session"""
        return self.log_dir / f"{slug}.log"

    def attach_command(self, slug: str) -> str:
        """Get the command to attach to a session"""
        return f"screen -r {slug}"
