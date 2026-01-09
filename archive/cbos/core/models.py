"""Pydantic models for CBOS"""

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class SessionType(str, Enum):
    """
    Type of Claude Code session.

    NOTE: As of v2.0, JSON mode is the only supported mode.
    Screen mode is deprecated and kept for backwards compatibility only.
    """
    JSON = "json"      # JSON streaming mode (active, recommended)
    SCREEN = "screen"  # DEPRECATED: Traditional screen-based session


class SessionState(str, Enum):
    """State of a Claude Code session"""

    WAITING = "waiting"  # Claude waiting for user input (> prompt visible)
    THINKING = "thinking"  # Claude is processing (spinner visible)
    WORKING = "working"  # Claude executing tools
    IDLE = "idle"  # Session idle, no recent activity
    ERROR = "error"  # Session in error state
    UNKNOWN = "unknown"  # Cannot determine state


class Session(BaseModel):
    """
    Represents a Claude Code session.

    Sessions use JSON streaming mode (`claude -p --output-format stream-json`).
    Legacy screen sessions are supported for backwards compatibility.
    """

    slug: str  # e.g., "AUTH", "INTEL"
    path: str = ""  # Working directory
    session_type: SessionType = SessionType.JSON  # Default to JSON mode
    state: SessionState = SessionState.IDLE
    claude_session_id: Optional[str] = None  # Claude's internal session ID for --resume
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)

    # DEPRECATED: Legacy screen mode fields (kept for backwards compatibility)
    screen_id: str = ""  # e.g., "900379.AUTH" - only for screen mode
    pid: Optional[int] = None  # Screen process PID
    last_question: Optional[str] = None  # Last question Claude asked (screen mode heuristic)
    buffer_tail: Optional[str] = None  # Last N lines of buffer (screen mode)
    attached: bool = False  # Whether screen session is attached


class StashedResponse(BaseModel):
    """A response saved for later delivery to a session"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_slug: str
    question: str  # What Claude asked
    response: str  # User's stashed response
    created_at: datetime = Field(default_factory=datetime.now)
    applied: bool = False


class SessionCreate(BaseModel):
    """
    Request to create a new session.

    NOTE: session_type is ignored - all sessions are now JSON mode.
    The parameter is kept for backwards compatibility.
    """

    slug: str
    path: str
    session_type: SessionType = SessionType.JSON  # DEPRECATED: Always JSON now


class SendInput(BaseModel):
    """Request to send input to a session"""

    text: str


class InvokeRequest(BaseModel):
    """Request to invoke Claude on a JSON session"""

    prompt: str
    skip_permissions: bool = True  # Use --dangerously-skip-permissions
    model: Optional[str] = None  # Override model (e.g., "opus", "sonnet")
    max_turns: Optional[int] = None  # Limit agentic turns


class SessionStatus(BaseModel):
    """Summary status for dashboard views"""

    total: int = 0
    waiting: int = 0
    thinking: int = 0
    working: int = 0
    idle: int = 0
    error: int = 0

    @classmethod
    def from_sessions(cls, sessions: list[Session]) -> "SessionStatus":
        status = cls(total=len(sessions))
        for s in sessions:
            match s.state:
                case SessionState.WAITING:
                    status.waiting += 1
                case SessionState.THINKING:
                    status.thinking += 1
                case SessionState.WORKING:
                    status.working += 1
                case SessionState.IDLE:
                    status.idle += 1
                case SessionState.ERROR:
                    status.error += 1
        return status


class WSMessage(BaseModel):
    """WebSocket message format"""

    type: str  # "init", "refresh", "send", "alert"
    sessions: Optional[list[Session]] = None
    slug: Optional[str] = None
    text: Optional[str] = None
    alert: Optional[str] = None
