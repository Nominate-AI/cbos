"""Pydantic models for CBOS"""

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class SessionState(str, Enum):
    """State of a Claude Code session"""

    WAITING = "waiting"  # Claude waiting for user input (> prompt visible)
    THINKING = "thinking"  # Claude is processing (spinner visible)
    WORKING = "working"  # Claude executing tools
    IDLE = "idle"  # Session idle, no recent activity
    ERROR = "error"  # Session in error state
    UNKNOWN = "unknown"  # Cannot determine state


class Session(BaseModel):
    """Represents a Claude Code session running in GNU Screen"""

    slug: str  # e.g., "AUTH", "INTEL"
    path: str = ""  # Working directory
    screen_id: str = ""  # e.g., "900379.AUTH"
    state: SessionState = SessionState.UNKNOWN
    pid: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)
    last_question: Optional[str] = None  # Last question Claude asked (if waiting)
    buffer_tail: Optional[str] = None  # Last N lines of buffer
    attached: bool = False  # Whether session is attached to a terminal


class StashedResponse(BaseModel):
    """A response saved for later delivery to a session"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_slug: str
    question: str  # What Claude asked
    response: str  # User's stashed response
    created_at: datetime = Field(default_factory=datetime.now)
    applied: bool = False


class SessionCreate(BaseModel):
    """Request to create a new session"""

    slug: str
    path: str


class SendInput(BaseModel):
    """Request to send input to a session"""

    text: str


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
