"""
JSON-based session manager for Claude Code.

Uses Claude's `--output-format stream-json` for structured output
instead of screen scraping.

Usage:
    manager = JSONSessionManager()
    session = manager.create_session("AUTH", "/path/to/project")
    
    async for event in manager.invoke("AUTH", "Fix the bug in main.py"):
        print(event)
        # {"type": "assistant", "message": {"content": "I'll look at..."}}
        # {"type": "tool_use", "tool": {"name": "Read", ...}}
        # {"type": "result", "subtype": "success", ...}
"""

import asyncio
import json
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Callable, Optional, Awaitable

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
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
    state: SessionState = SessionState.IDLE
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
StateCallback = Callable[[str, SessionState], Awaitable[None]]


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
        claude_command: str = "claude",
        env_vars: Optional[dict] = None,
    ):
        """
        Args:
            claude_command: Path to claude CLI (default: "claude")
            env_vars: Additional environment variables for Claude process
        """
        self.claude_command = claude_command
        self.env_vars = env_vars or {}
        
        self._sessions: dict[str, JSONSession] = {}
        self._event_callbacks: list[EventCallback] = []
        self._state_callbacks: list[StateCallback] = []
    
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
            raise ValueError(f"Session '{slug}' already exists")
        
        session = JSONSession(slug=slug, path=path)
        self._sessions[slug] = session
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
            raise ValueError(f"Session '{slug}' not found")
        
        if session.state == SessionState.RUNNING:
            raise ValueError(f"Session '{slug}' is already running")
        
        # Build command
        cmd = [self.claude_command, "-p", prompt, "--output-format", "stream-json"]
        
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
        session.state = SessionState.RUNNING
        session.last_activity = datetime.now()
        await self._emit_state(slug, SessionState.RUNNING)
        
        logger.info(f"[{slug}] Invoking Claude: {' '.join(cmd[:5])}...")
        
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
                    logger.debug(f"[{slug}] Got session ID: {session.claude_session_id}")
                
                yield event
                await self._emit_event(slug, event)
            
            # Wait for process to complete
            await process.wait()
            
            if process.returncode == 0:
                session.state = SessionState.COMPLETE
                logger.info(f"[{slug}] Invocation completed successfully")
            else:
                stderr = await process.stderr.read()
                error_msg = stderr.decode('utf-8')
                session.state = SessionState.ERROR
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
            session.state = SessionState.ERROR
            raise
        
        except Exception as e:
            session.state = SessionState.ERROR
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
            session.state = SessionState.IDLE
            await self._emit_state(slug, SessionState.IDLE)
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
    
    async def _emit_state(self, slug: str, state: SessionState) -> None:
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


# =============================================================================
# Example Usage
# =============================================================================

async def example():
    """Example usage of JSONSessionManager"""
    
    manager = JSONSessionManager(claude_command="claude")
    
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
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(example())
