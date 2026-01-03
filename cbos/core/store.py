"""Session store - manages session state and persistence"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

from .models import Session, SessionState, StashedResponse
from .screen import ScreenManager

logger = logging.getLogger(__name__)


class SessionStore:
    """
    In-memory session store with JSON persistence.

    Syncs with actual GNU Screen sessions and maintains state.
    """

    def __init__(
        self,
        persist_path: Optional[Path] = None,
        screen_manager: Optional[ScreenManager] = None,
    ):
        self.persist_path = persist_path or Path.home() / ".cbos" / "sessions.json"
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)

        self.screen = screen_manager or ScreenManager()

        self._sessions: dict[str, Session] = {}
        self._stash: dict[str, StashedResponse] = {}
        self._path_map: dict[str, str] = {}  # slug -> path (user-configured)

        self._load()

    def _load(self):
        """Load persisted session data"""
        if self.persist_path.exists():
            try:
                data = json.loads(self.persist_path.read_text())

                # Load path mappings
                self._path_map = data.get("path_map", {})

                # Load stashed responses
                for s in data.get("stash", []):
                    stash = StashedResponse(**s)
                    self._stash[stash.id] = stash

            except Exception as e:
                logger.warning(f"Failed to load persisted data: {e}")

    def _save(self):
        """Persist session data"""
        data = {
            "path_map": self._path_map,
            "stash": [r.model_dump(mode="json") for r in self._stash.values()],
        }
        self.persist_path.write_text(json.dumps(data, indent=2, default=str))

    def sync_with_screen(self) -> list[Session]:
        """
        Sync stored sessions with actual screen sessions.

        Discovers new sessions, removes dead ones, updates PIDs.
        """
        screen_sessions = self.screen.list_sessions()
        screen_map = {s.name: s for s in screen_sessions}

        # Remove sessions that no longer exist in screen
        dead_slugs = [slug for slug in self._sessions if slug not in screen_map]
        for slug in dead_slugs:
            del self._sessions[slug]

        # Update existing and add new sessions
        for screen_session in screen_sessions:
            slug = screen_session.name

            if slug in self._sessions:
                # Update existing
                session = self._sessions[slug]
                session.screen_id = screen_session.screen_id
                session.pid = screen_session.pid
                session.attached = screen_session.attached
            else:
                # New session discovered
                session = Session(
                    slug=slug,
                    path=self._path_map.get(slug, ""),
                    screen_id=screen_session.screen_id,
                    pid=screen_session.pid,
                    attached=screen_session.attached,
                )
                self._sessions[slug] = session

        return list(self._sessions.values())

    def refresh_states(self) -> list[Session]:
        """Update state for all sessions by reading buffers"""
        for session in self._sessions.values():
            try:
                buffer = self.screen.capture_buffer(session.slug)
                session.buffer_tail = buffer
                state, question = self.screen.detect_state(buffer)
                session.state = state
                session.last_question = question
                session.last_activity = datetime.now()
            except Exception as e:
                logger.warning(f"Failed to refresh state for {session.slug}: {e}")
                session.state = SessionState.ERROR

        return list(self._sessions.values())

    def get(self, slug: str) -> Optional[Session]:
        """Get a session by slug"""
        return self._sessions.get(slug)

    def all(self) -> list[Session]:
        """Get all sessions"""
        return list(self._sessions.values())

    def waiting(self) -> list[Session]:
        """Get sessions that are waiting for input"""
        return [s for s in self._sessions.values() if s.state == SessionState.WAITING]

    def create(self, slug: str, path: str, resume: bool = False) -> Session:
        """Create a new Claude Code session"""
        screen_session = self.screen.launch(slug, path, resume=resume)

        session = Session(
            slug=slug,
            path=path,
            screen_id=screen_session.screen_id,
            pid=screen_session.pid,
            attached=screen_session.attached,
        )

        self._sessions[slug] = session
        self._path_map[slug] = path
        self._save()

        return session

    def delete(self, slug: str) -> bool:
        """Delete a session (kills the screen session)"""
        if slug in self._sessions:
            self.screen.kill(slug)
            del self._sessions[slug]
            return True
        return False

    def send_input(self, slug: str, text: str) -> bool:
        """Send input to a session"""
        if slug not in self._sessions:
            return False
        return self.screen.send_input(slug, text)

    def send_interrupt(self, slug: str) -> bool:
        """Send Ctrl+C to a session"""
        if slug not in self._sessions:
            return False
        return self.screen.send_interrupt(slug)

    def set_path(self, slug: str, path: str):
        """Set the working directory path for a session"""
        if slug in self._sessions:
            self._sessions[slug].path = path
        self._path_map[slug] = path
        self._save()

    def get_buffer(self, slug: str, lines: int = 100) -> str:
        """Get the buffer content for a session"""
        return self.screen.capture_buffer(slug, lines)

    # Stash management

    def stash_response(
        self, session_slug: str, question: str, response: str
    ) -> StashedResponse:
        """Save a response for later"""
        stash = StashedResponse(
            session_slug=session_slug,
            question=question,
            response=response,
        )
        self._stash[stash.id] = stash
        self._save()
        return stash

    def get_stash(self, stash_id: str) -> Optional[StashedResponse]:
        """Get a stashed response by ID"""
        return self._stash.get(stash_id)

    def list_stash(self, session_slug: Optional[str] = None) -> list[StashedResponse]:
        """List stashed responses, optionally filtered by session"""
        stashes = list(self._stash.values())
        if session_slug:
            stashes = [s for s in stashes if s.session_slug == session_slug]
        return [s for s in stashes if not s.applied]

    def apply_stash(self, stash_id: str) -> bool:
        """Apply a stashed response (send it to the session)"""
        stash = self._stash.get(stash_id)
        if not stash:
            return False

        success = self.send_input(stash.session_slug, stash.response)
        if success:
            stash.applied = True
            self._save()

        return success

    def delete_stash(self, stash_id: str) -> bool:
        """Delete a stashed response"""
        if stash_id in self._stash:
            del self._stash[stash_id]
            self._save()
            return True
        return False
