"""
JSON-based session manager for Claude Code.

Uses Claude's `--output-format stream-json` for structured output
instead of screen scraping.

Usage:
    manager = JSONSessionManager()
    session = manager.create_session("AUTH", "/path/to/project")

    async for event in manager.invoke("AUTH", "Fix the bug in main.py"):
        print(event)
        # ClaudeEvent(type="assistant", data={"message": {"content": "I'll look at..."}})
        # ClaudeEvent(type="tool_use", data={"tool": {"name": "Read", ...}})
        # ClaudeEvent(type="result", data={"subtype": "success", ...})
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Callable, Optional, Awaitable

from .logging import get_logger
from .config import get_config

logger = get_logger("json_manager")


class JSONSessionState(str, Enum):
    """State of a JSON-mode Claude session"""
    IDLE = "idle"           # Ready for new prompt
    RUNNING = "running"     # Claude process executing
    COMPLETE = "complete"   # Last invocation finished
    ERROR = "error"         # Error occurred


@dataclass
class ClaudeEvent:
    """A parsed event from Claude's stream-json output"""
    type: str
    data: dict
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    raw: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp,
        }


@dataclass
class JSONSession:
    """Represents a Claude Code session using JSON streaming"""
    slug: str
    path: str
    claude_session_id: Optional[str] = None  # Claude's internal session ID
    state: JSONSessionState = JSONSessionState.IDLE
    events: list[ClaudeEvent] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    # Process management
    _process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "path": self.path,
            "claude_session_id": self.claude_session_id,
            "state": self.state.value,
            "event_count": len(self.events),
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
        }


# Type for event callbacks
EventCallback = Callable[[str, ClaudeEvent], Awaitable[None]]
StateCallback = Callable[[str, JSONSessionState], Awaitable[None]]


class JSONSessionManager:
    """
    Manages Claude Code sessions using JSON streaming mode.

    Instead of running interactive Claude sessions and scraping terminal output,
    this manager runs repeated non-interactive invocations that resume the same
    conversation using Claude's --resume flag.

    Benefits:
    - Structured JSON output (no ANSI code stripping)
    - Clear event types (assistant, tool_use, result, etc.)
    - Explicit state transitions
    - Easy WebSocket broadcasting
    """

    def __init__(
        self,
        claude_command: Optional[str] = None,
        env_vars: Optional[dict] = None,
    ):
        """
        Args:
            claude_command: Path to claude CLI (default from config)
            env_vars: Additional environment variables for Claude process
        """
        config = get_config()
        self.claude_command = claude_command or config.claude_command

        # Parse env vars from config
        self.env_vars = env_vars or {}
        if config.claude_env_vars:
            for pair in config.claude_env_vars.split():
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    self.env_vars[key] = value

        self._sessions: dict[str, JSONSession] = {}
        self._event_callbacks: list[EventCallback] = []
        self._state_callbacks: list[StateCallback] = []

        # Persistence
        self._persist_path = Path.home() / ".cbos" / "json_sessions.json"
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

        logger.info(f"JSONSessionManager initialized with command: {self.claude_command}")

    # =========================================================================
    # Persistence
    # =========================================================================

    def _load(self) -> None:
        """Load persisted session data"""
        if self._persist_path.exists():
            try:
                data = json.loads(self._persist_path.read_text())
                for slug, session_data in data.get("sessions", {}).items():
                    session = JSONSession(
                        slug=slug,
                        path=session_data.get("path", ""),
                        claude_session_id=session_data.get("claude_session_id"),
                        state=JSONSessionState.IDLE,  # Reset state on load
                        created_at=datetime.fromisoformat(session_data.get("created_at", datetime.now().isoformat())),
                    )
                    self._sessions[slug] = session
                logger.info(f"Loaded {len(self._sessions)} JSON sessions from disk")
            except Exception as e:
                logger.warning(f"Failed to load JSON sessions: {e}")

    def _save(self) -> None:
        """Persist session data"""
        data = {
            "sessions": {
                slug: {
                    "path": s.path,
                    "claude_session_id": s.claude_session_id,
                    "created_at": s.created_at.isoformat(),
                }
                for slug, s in self._sessions.items()
            }
        }
        self._persist_path.write_text(json.dumps(data, indent=2))

    # =========================================================================
    # Session Management
    # =========================================================================

    def create_session(self, slug: str, path: str) -> JSONSession:
        """
        Create a new session.

        Note: This just creates metadata. The actual Claude process is
        spawned when invoke() is called.
        """
        if slug in self._sessions:
            raise ValueError(f"JSON session '{slug}' already exists")

        session = JSONSession(slug=slug, path=path)
        self._sessions[slug] = session
        self._save()
        logger.info(f"Created JSON session: {slug} at {path}")
        return session

    def get_session(self, slug: str) -> Optional[JSONSession]:
        """Get a session by slug"""
        return self._sessions.get(slug)

    def list_sessions(self) -> list[JSONSession]:
        """List all sessions"""
        return list(self._sessions.values())

    def delete_session(self, slug: str) -> bool:
        """Delete a session (kills process if running)"""
        session = self._sessions.pop(slug, None)
        if session:
            if session._process and session._process.returncode is None:
                session._process.terminate()
            self._save()
            logger.info(f"Deleted JSON session: {slug}")
            return True
        return False

    # =========================================================================
    # Claude Invocation
    # =========================================================================

    async def invoke(
        self,
        slug: str,
        prompt: str,
        skip_permissions: bool = True,
        model: Optional[str] = None,
        max_turns: Optional[int] = None,
    ) -> AsyncIterator[ClaudeEvent]:
        """
        Invoke Claude with a prompt and stream events.

        This spawns a Claude CLI process with --output-format stream-json,
        parses the JSON output line by line, and yields ClaudeEvent objects.

        Args:
            slug: Session identifier
            prompt: The prompt to send to Claude
            skip_permissions: Use --dangerously-skip-permissions (default: True)
            model: Override model (e.g., "opus", "sonnet")
            max_turns: Limit agentic turns

        Yields:
            ClaudeEvent objects as they arrive
        """
        session = self._sessions.get(slug)
        if not session:
            raise ValueError(f"JSON session '{slug}' not found")

        if session.state == JSONSessionState.RUNNING:
            raise ValueError(f"JSON session '{slug}' is already running")

        # Build command
        # --verbose is required when using -p with --output-format stream-json
        cmd = [self.claude_command, "-p", prompt, "--output-format", "stream-json", "--verbose"]

        if skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        if model:
            cmd.extend(["--model", model])

        if max_turns:
            cmd.extend(["--max-turns", str(max_turns)])

        # Resume existing session or start new
        if session.claude_session_id:
            cmd.extend(["--resume", session.claude_session_id])
            logger.debug(f"[{slug}] Resuming session: {session.claude_session_id}")

        # Prepare environment
        env = {**os.environ, "NO_COLOR": "1", **self.env_vars}

        # Update state
        session.state = JSONSessionState.RUNNING
        session.last_activity = datetime.now()
        await self._emit_state(slug, JSONSessionState.RUNNING)

        logger.info(f"[{slug}] Invoking Claude: {' '.join(cmd[:6])}...")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=session.path,
                env=env,
            )
            session._process = process

            # Stream stdout line by line
            async for line in process.stdout:
                line_str = line.decode('utf-8').strip()
                if not line_str:
                    continue

                event = self._parse_event(line_str)
                session.events.append(event)
                session.last_activity = datetime.now()

                # Extract session_id from init event
                if event.type == "init" and "session_id" in event.data:
                    session.claude_session_id = event.data["session_id"]
                    self._save()  # Persist session ID immediately
                    logger.debug(f"[{slug}] Got session ID: {session.claude_session_id}")

                yield event
                await self._emit_event(slug, event)

            # Wait for process to complete
            await process.wait()

            if process.returncode == 0:
                session.state = JSONSessionState.COMPLETE
                logger.info(f"[{slug}] Invocation completed successfully")
            else:
                stderr = await process.stderr.read()
                error_msg = stderr.decode('utf-8')
                session.state = JSONSessionState.ERROR
                logger.error(f"[{slug}] Claude exited with error: {error_msg}")

                error_event = ClaudeEvent(
                    type="error",
                    data={"message": error_msg, "returncode": process.returncode},
                    raw=error_msg,
                )
                yield error_event
                await self._emit_event(slug, error_event)

        except asyncio.CancelledError:
            if session._process and session._process.returncode is None:
                session._process.terminate()
            session.state = JSONSessionState.ERROR
            raise

        except Exception as e:
            session.state = JSONSessionState.ERROR
            logger.exception(f"[{slug}] Error during invocation")
            error_event = ClaudeEvent(type="error", data={"message": str(e)})
            yield error_event
            await self._emit_event(slug, error_event)

        finally:
            session._process = None
            await self._emit_state(slug, session.state)

    def _parse_event(self, line: str) -> ClaudeEvent:
        """Parse a JSON line into a ClaudeEvent"""
        try:
            data = json.loads(line)
            event_type = data.pop("type", "unknown")
            return ClaudeEvent(type=event_type, data=data, raw=line)
        except json.JSONDecodeError:
            # Non-JSON output - wrap it
            return ClaudeEvent(type="raw", data={"content": line}, raw=line)

    # =========================================================================
    # Interrupt / Cancel
    # =========================================================================

    async def interrupt(self, slug: str) -> bool:
        """
        Interrupt a running Claude process.

        Note: Unlike interactive mode, there's no way to gracefully interrupt
        a non-interactive Claude invocation. This terminates the process.
        """
        session = self._sessions.get(slug)
        if not session:
            return False

        if session._process and session._process.returncode is None:
            session._process.terminate()
            session.state = JSONSessionState.IDLE
            await self._emit_state(slug, JSONSessionState.IDLE)
            logger.info(f"[{slug}] Process terminated")
            return True

        return False

    # =========================================================================
    # Event Callbacks
    # =========================================================================

    def on_event(self, callback: EventCallback) -> None:
        """Register callback for Claude events"""
        self._event_callbacks.append(callback)

    def on_state_change(self, callback: StateCallback) -> None:
        """Register callback for state changes"""
        self._state_callbacks.append(callback)

    async def _emit_event(self, slug: str, event: ClaudeEvent) -> None:
        """Notify callbacks of a new event"""
        for callback in self._event_callbacks:
            try:
                await callback(slug, event)
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    async def _emit_state(self, slug: str, state: JSONSessionState) -> None:
        """Notify callbacks of state change"""
        for callback in self._state_callbacks:
            try:
                await callback(slug, state)
            except Exception as e:
                logger.error(f"State callback error: {e}")

    # =========================================================================
    # Event History
    # =========================================================================

    def get_events(
        self,
        slug: str,
        limit: Optional[int] = None,
        event_type: Optional[str] = None,
    ) -> list[ClaudeEvent]:
        """
        Get events for a session.

        Args:
            slug: Session identifier
            limit: Max number of events (from end)
            event_type: Filter by type (e.g., "assistant", "tool_use")
        """
        session = self._sessions.get(slug)
        if not session:
            return []

        events = session.events

        if event_type:
            events = [e for e in events if e.type == event_type]

        if limit:
            events = events[-limit:]

        return events

    def get_last_response(self, slug: str) -> Optional[str]:
        """Get the last assistant response text"""
        events = self.get_events(slug, event_type="assistant")
        if events:
            last = events[-1]
            message = last.data.get("message", {})
            if isinstance(message, dict):
                return message.get("content", "")
            return str(message)
        return None

    def clear_events(self, slug: str) -> None:
        """Clear event history for a session"""
        session = self._sessions.get(slug)
        if session:
            session.events.clear()
            logger.debug(f"[{slug}] Cleared event history")

    # =========================================================================
    # Format events for display
    # =========================================================================

    def format_event_for_display(self, event: ClaudeEvent) -> str:
        """Format a ClaudeEvent for terminal display"""
        event_type = event.type
        data = event.data

        if event_type == "init":
            session_id = data.get("session_id", "")[:8]
            return f"[Session: {session_id}...]\n"

        elif event_type == "user":
            message = data.get("message", "")
            return f"\n> {message}\n"

        elif event_type == "assistant":
            message = data.get("message", {})
            content = message.get("content", "") if isinstance(message, dict) else str(message)
            return f"\n{content}\n"

        elif event_type == "tool_use":
            tool = data.get("tool", {})
            name = tool.get("name", "unknown")
            tool_input = tool.get("input", {})
            # Show abbreviated input
            input_preview = str(tool_input)[:100]
            if len(str(tool_input)) > 100:
                input_preview += "..."
            return f"\n[Tool: {name}] {input_preview}\n"

        elif event_type == "tool_result":
            result = data.get("result", "")
            preview = str(result)[:200]
            if len(str(result)) > 200:
                preview += "..."
            return f"[Result] {preview}\n"

        elif event_type == "result":
            subtype = data.get("subtype", "")
            cost = data.get("cost_usd", 0)
            duration = data.get("duration_ms", 0)
            return f"\n[{subtype.upper()}] Cost: ${cost:.4f}, Duration: {duration}ms\n"

        elif event_type == "error":
            message = data.get("message", "Unknown error")
            return f"\n[ERROR] {message}\n"

        elif event_type == "raw":
            content = data.get("content", "")
            return f"{content}\n"

        else:
            return f"[{event_type}] {data}\n"


# =============================================================================
# Example Usage
# =============================================================================

async def example():
    """Example usage of JSONSessionManager"""

    manager = JSONSessionManager()

    # Create session
    session = manager.create_session("TEST", "/home/user/project")
    print(f"Created session: {session.to_dict()}")

    # Register event handler
    async def on_event(slug: str, event: ClaudeEvent):
        print(f"[{slug}] {event.type}: {event.data}")

    manager.on_event(on_event)

    # First invocation
    print("\n--- First invocation ---")
    async for event in manager.invoke("TEST", "What files are in this directory?"):
        pass  # Events are printed by callback

    print(f"\nSession state: {session.state}")
    print(f"Session ID: {session.claude_session_id}")

    # Second invocation (continues same session)
    print("\n--- Second invocation ---")
    async for event in manager.invoke("TEST", "Read the README"):
        pass

    print(f"\nTotal events: {len(session.events)}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(example())
