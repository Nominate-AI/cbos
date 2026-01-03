"""Tests for ScreenManager"""

import pytest
from cbos.core.screen import ScreenManager
from cbos.core.models import SessionState


class TestStateDetection:
    """Test Claude Code state detection from buffer"""

    def setup_method(self):
        self.manager = ScreenManager()

    def test_detect_waiting_empty_prompt(self):
        """Detect waiting state from empty > prompt"""
        buffer = """
Some previous output from Claude.
This is a question for you?

>
"""
        state, question = self.manager.detect_state(buffer)
        assert state == SessionState.WAITING
        assert question is not None

    def test_detect_waiting_with_space(self):
        """Detect waiting state from > with trailing space"""
        buffer = """
Would you like me to continue?

> """
        state, question = self.manager.detect_state(buffer)
        assert state == SessionState.WAITING

    def test_detect_thinking(self):
        """Detect thinking state from spinner"""
        buffer = """
Let me analyze this code...

● Thinking about the implementation
"""
        state, _ = self.manager.detect_state(buffer)
        assert state == SessionState.THINKING

    def test_detect_working(self):
        """Detect working state from tool execution"""
        buffer = """
I'll read that file for you.

Read(/home/user/project/src/main.py)
"""
        state, _ = self.manager.detect_state(buffer)
        assert state == SessionState.WORKING

    def test_detect_working_bash(self):
        """Detect working state from Bash tool"""
        buffer = """
Running the tests now.

Bash(pytest tests/ -v)
"""
        state, _ = self.manager.detect_state(buffer)
        assert state == SessionState.WORKING

    def test_detect_error(self):
        """Detect error state"""
        buffer = """
Error: Failed to connect to the server.
Please check your network connection.
"""
        state, _ = self.manager.detect_state(buffer)
        assert state == SessionState.ERROR

    def test_detect_idle(self):
        """Detect idle state when no patterns match"""
        buffer = """
Done! The file has been updated.

All changes have been saved.
"""
        state, _ = self.manager.detect_state(buffer)
        assert state == SessionState.IDLE

    def test_empty_buffer(self):
        """Handle empty buffer"""
        state, _ = self.manager.detect_state("")
        assert state == SessionState.UNKNOWN

    def test_extract_question(self):
        """Extract the question Claude asked"""
        buffer = """
I've analyzed the code and found a few issues.

Would you like me to:
1. Fix the type errors
2. Add missing imports
3. Both

>
"""
        state, question = self.manager.detect_state(buffer)
        assert state == SessionState.WAITING
        assert "Would you like me to" in question
        assert "1. Fix the type errors" in question

    def test_skip_noise_lines(self):
        """Skip Agent pid and Identity lines when extracting questions"""
        buffer = """
Done! Changes complete.

Agent pid 12345
Identity added: /home/user/.ssh/key

What would you like to do next?

>
"""
        state, question = self.manager.detect_state(buffer)
        assert state == SessionState.WAITING
        assert "Agent pid" not in question
        assert "Identity added" not in question
        assert "What would you like to do next?" in question


class TestScreenManagerIntegration:
    """Integration tests that require actual screen sessions"""

    def setup_method(self):
        self.manager = ScreenManager()

    def test_list_sessions(self):
        """List actual running screen sessions"""
        sessions = self.manager.list_sessions()
        # Should return a list (may be empty if no sessions)
        assert isinstance(sessions, list)

    def test_list_sessions_structure(self):
        """Verify session structure when sessions exist"""
        sessions = self.manager.list_sessions()
        if sessions:
            session = sessions[0]
            assert hasattr(session, "pid")
            assert hasattr(session, "name")
            assert hasattr(session, "screen_id")
            assert hasattr(session, "attached")
            assert isinstance(session.pid, int)


class TestBufferCapture:
    """Test buffer capture (requires running session)"""

    def setup_method(self):
        self.manager = ScreenManager()

    def test_capture_existing_session(self):
        """Capture buffer from an existing session"""
        sessions = self.manager.list_sessions()
        if not sessions:
            pytest.skip("No screen sessions running")

        slug = sessions[0].name
        buffer = self.manager.capture_buffer(slug)

        assert isinstance(buffer, str)
        # Buffer should not contain raw ANSI codes
        assert "\x1b[" not in buffer
