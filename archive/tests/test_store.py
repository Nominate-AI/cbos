"""Tests for SessionStore"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from cbos.core.store import SessionStore
from cbos.core.models import SessionState


class TestSessionStore:
    """Test SessionStore functionality"""

    def test_sync_discovers_sessions(self):
        """Sync should discover running screen sessions"""
        store = SessionStore()
        sessions = store.sync_with_screen()

        # Should return a list
        assert isinstance(sessions, list)

    def test_persistence(self):
        """Test that path mappings persist"""
        with TemporaryDirectory() as tmpdir:
            persist_path = Path(tmpdir) / "sessions.json"

            # Create store and set a path
            store1 = SessionStore(persist_path=persist_path)
            store1._path_map["TEST"] = "/some/path"
            store1._save()

            # Create new store and verify path loaded
            store2 = SessionStore(persist_path=persist_path)
            assert store2._path_map.get("TEST") == "/some/path"

    def test_stash_response(self):
        """Test stashing a response"""
        with TemporaryDirectory() as tmpdir:
            persist_path = Path(tmpdir) / "sessions.json"
            store = SessionStore(persist_path=persist_path)

            stash = store.stash_response(
                session_slug="AUTH",
                question="Which approach?",
                response="Option 1",
            )

            assert stash.session_slug == "AUTH"
            assert stash.question == "Which approach?"
            assert stash.response == "Option 1"
            assert not stash.applied

    def test_list_stash(self):
        """Test listing stashed responses"""
        with TemporaryDirectory() as tmpdir:
            persist_path = Path(tmpdir) / "sessions.json"
            store = SessionStore(persist_path=persist_path)

            store.stash_response("AUTH", "Q1", "R1")
            store.stash_response("INTEL", "Q2", "R2")
            store.stash_response("AUTH", "Q3", "R3")

            # List all
            all_stash = store.list_stash()
            assert len(all_stash) == 3

            # Filter by session
            auth_stash = store.list_stash("AUTH")
            assert len(auth_stash) == 2

    def test_delete_stash(self):
        """Test deleting a stashed response"""
        with TemporaryDirectory() as tmpdir:
            persist_path = Path(tmpdir) / "sessions.json"
            store = SessionStore(persist_path=persist_path)

            stash = store.stash_response("AUTH", "Q1", "R1")
            assert len(store.list_stash()) == 1

            store.delete_stash(stash.id)
            assert len(store.list_stash()) == 0

    def test_get_waiting_sessions(self):
        """Test getting sessions that are waiting"""
        store = SessionStore()
        store.sync_with_screen()
        store.refresh_states()

        waiting = store.waiting()
        assert isinstance(waiting, list)
        for session in waiting:
            assert session.state == SessionState.WAITING


class TestSessionStoreIntegration:
    """Integration tests that modify actual sessions"""

    @pytest.fixture
    def store(self):
        return SessionStore()

    def test_get_buffer(self, store):
        """Get buffer from a running session"""
        store.sync_with_screen()
        sessions = store.all()

        if not sessions:
            pytest.skip("No screen sessions running")

        buffer = store.get_buffer(sessions[0].slug)
        assert isinstance(buffer, str)

    def test_refresh_updates_states(self, store):
        """Refresh should update session states"""
        store.sync_with_screen()
        sessions_before = store.all()

        if not sessions_before:
            pytest.skip("No screen sessions running")

        store.refresh_states()
        sessions_after = store.all()

        # States should be set to something other than UNKNOWN
        for session in sessions_after:
            # At least some sessions should have known states
            if session.buffer_tail:
                assert session.state != SessionState.UNKNOWN or len(session.buffer_tail) < 10
