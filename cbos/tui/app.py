"""CBOS TUI - Claude Code Session Manager"""

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

import httpx
import websockets
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Header,
    Footer,
    Static,
    ListView,
    ListItem,
    Input,
    Label,
    Rule,
    Button,
)
from textual import work
from rich.text import Text
from rich.panel import Panel

from ..core.version import get_version_string


def discover_claude_projects(active_paths: set[str]) -> list[dict]:
    """
    Discover Claude projects by finding CLAUDE.md files.

    Returns list of dicts with 'path', 'name', 'mtime' sorted by mtime desc.
    Filters out paths that are already active sessions.
    """
    home = Path.home()
    projects = []

    try:
        # Find all CLAUDE.md files
        result = subprocess.run(
            ["find", str(home), "-type", "f", "-name", "CLAUDE.md",
             "-not", "-path", "*/.*"],  # Exclude hidden directories
            capture_output=True,
            text=True,
            timeout=30,
        )

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            claude_md = Path(line)
            project_dir = claude_md.parent
            project_path = str(project_dir)

            # Skip if already an active session
            if project_path in active_paths:
                continue

            # Get modification time
            try:
                mtime = claude_md.stat().st_mtime
            except OSError:
                continue

            # Generate session name from git config
            session_name = generate_session_name(project_dir)

            projects.append({
                "path": project_path,
                "name": session_name,
                "mtime": mtime,
                "display": f"{session_name} ({project_path})",
            })

        # Sort by mtime descending (most recent first)
        projects.sort(key=lambda x: x["mtime"], reverse=True)

    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

    return projects


def generate_session_name(project_dir: Path) -> str:
    """
    Generate session name from git remote origin URL.
    Falls back to directory name if git config not available.
    """
    git_config = project_dir / ".git" / "config"

    if git_config.exists():
        try:
            content = git_config.read_text()
            for line in content.split("\n"):
                if "url =" in line:
                    # Extract URL and get repo name
                    url = line.split("=")[-1].strip()
                    # Handle various URL formats:
                    # git@github.com:user/repo.git
                    # https://github.com/user/repo.git
                    repo_name = url.split("/")[-1]
                    if repo_name.endswith(".git"):
                        repo_name = repo_name[:-4]
                    return repo_name.upper()
        except Exception:
            pass

    # Fallback to directory name
    return project_dir.name.upper()


class ProjectItem(ListItem):
    """A project in the selection list"""

    def __init__(self, project: dict) -> None:
        super().__init__()
        self.project = project

    def compose(self) -> ComposeResult:
        text = Text()
        text.append(self.project["name"], style="bold cyan")
        text.append("\n")
        text.append(self.project["path"], style="dim")
        yield Static(text)


class CreateSessionScreen(ModalScreen[dict | None]):
    """Modal screen for selecting a project to create a session"""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("n", "next_page", "Next"),
        Binding("p", "prev_page", "Prev"),
    ]

    CSS = """
    CreateSessionScreen {
        align: center middle;
    }

    #create-dialog {
        width: 80%;
        max-width: 100;
        height: 80%;
        max-height: 30;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #create-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #project-list {
        height: 1fr;
    }

    #project-list > ListItem {
        padding: 0 1;
    }

    #project-list > ListItem.--highlight {
        background: $accent;
    }

    #page-info {
        text-align: center;
        padding-top: 1;
        color: $text-muted;
    }

    #create-footer {
        text-align: center;
        padding-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, projects: list[dict], page_size: int = 10):
        super().__init__()
        self.all_projects = projects
        self.page_size = page_size
        self.current_page = 0
        self.total_pages = max(1, (len(projects) + page_size - 1) // page_size)

    def compose(self) -> ComposeResult:
        with Vertical(id="create-dialog"):
            yield Label("Create New Session", id="create-title")
            yield Rule()
            yield ListView(id="project-list")
            yield Static(id="page-info")
            yield Static("Enter=Select │ n/p=Page │ Esc=Cancel", id="create-footer")

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        """Refresh the project list for current page"""
        project_list = self.query_one("#project-list", ListView)
        project_list.clear()

        start = self.current_page * self.page_size
        end = start + self.page_size
        page_projects = self.all_projects[start:end]

        for project in page_projects:
            project_list.append(ProjectItem(project))

        # Update page info
        page_info = self.query_one("#page-info", Static)
        if self.total_pages > 1:
            page_info.update(f"Page {self.current_page + 1}/{self.total_pages} ({len(self.all_projects)} projects)")
        else:
            page_info.update(f"{len(self.all_projects)} projects found")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle project selection"""
        if isinstance(event.item, ProjectItem):
            self.dismiss(event.item.project)

    def action_cancel(self) -> None:
        """Cancel and close modal"""
        self.dismiss(None)

    def action_next_page(self) -> None:
        """Go to next page"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._refresh_list()

    def action_prev_page(self) -> None:
        """Go to previous page"""
        if self.current_page > 0:
            self.current_page -= 1
            self._refresh_list()

    def action_cursor_down(self) -> None:
        """Move cursor down in list"""
        project_list = self.query_one("#project-list", ListView)
        project_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in list"""
        project_list = self.query_one("#project-list", ListView)
        project_list.action_cursor_up()

API_BASE = "http://127.0.0.1:32205"
WS_STREAM_URL = "ws://127.0.0.1:32205/ws/stream"

# Maximum buffer size per session (characters)
MAX_BUFFER_SIZE = 50000

# ANSI escape code pattern for stripping terminal sequences
ANSI_ESCAPE_PATTERN = re.compile(r'''
    \x1b  # ESC character
    (?:   # Non-capturing group for different escape types
        \[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]  # CSI sequences (colors, cursor, etc.)
        |\].*?(?:\x07|\x1b\\)                   # OSC sequences (title, etc.)
        |[PX^_].*?\x1b\\                        # DCS, SOS, PM, APC sequences
        |\([\x20-\x7e]                          # Character set selection
        |[\x20-\x2f]*[\x30-\x7e]                # Other escape sequences
    )
''', re.VERBOSE)


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text"""
    # Remove ANSI escape sequences
    text = ANSI_ESCAPE_PATTERN.sub('', text)
    # Remove other control characters except newline, tab, carriage return
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text


# State icons with colors
STATE_STYLES = {
    "waiting": ("● ", "bold red"),
    "thinking": ("◐ ", "bold yellow"),
    "working": ("◑ ", "bold cyan"),
    "idle": ("○ ", "dim"),
    "error": ("✗ ", "bold red"),
    "unknown": ("? ", "dim"),
}


class SessionItem(ListItem):
    """A session in the list"""

    def __init__(self, session: dict) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        state = self.session.get("state", "unknown")
        icon, style = STATE_STYLES.get(state, STATE_STYLES["unknown"])
        slug = self.session.get("slug", "???")

        text = Text()
        text.append(icon, style=style)
        text.append(slug, style="bold" if state == "waiting" else "")

        yield Static(text)


class SessionList(ListView):
    """Session list with state indicators"""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]


class BufferView(ScrollableContainer):
    """Display session buffer content"""

    buffer = reactive("")
    question = reactive("")

    def compose(self) -> ComposeResult:
        yield Static(id="buffer-content", markup=False)
        yield Static(id="question-highlight")

    def watch_buffer(self, value: str) -> None:
        content = self.query_one("#buffer-content", Static)
        # Show last 100 lines, don't strip trailing whitespace
        lines = value.split("\n")[-100:]
        content.update("\n".join(lines))
        # Auto-scroll to bottom
        self.scroll_end(animate=False)

    def watch_question(self, value: str) -> None:
        highlight = self.query_one("#question-highlight", Static)
        if value:
            highlight.update(
                Panel(value, title="[bold yellow]Waiting for response[/]", border_style="yellow")
            )
        else:
            highlight.update("")


class SuggestionPanel(Static):
    """Display AI-generated response suggestion"""

    suggestion = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static(id="suggestion-content")

    def watch_suggestion(self, value) -> None:
        content = self.query_one("#suggestion-content", Static)
        if value:
            text = Text()
            text.append("AI Suggestion ", style="bold cyan")
            text.append(f"({value.get('confidence', 0):.0%} confident)\n", style="dim")
            text.append(value.get('response', ''), style="bold white")
            text.append(f"\n{value.get('reasoning', '')}", style="dim italic")

            alternatives = value.get('alternatives', [])
            if alternatives:
                text.append("\nAlternatives: ", style="dim")
                text.append(" | ".join(alternatives), style="dim")

            content.update(Panel(
                text,
                title="[bold cyan]💡 Suggestion[/] [dim](Enter=accept, e=edit, Esc=dismiss)[/]",
                border_style="cyan"
            ))
        else:
            content.update("")

    def clear(self) -> None:
        self.suggestion = None


class StatusLegend(Static):
    """Status legend for sidebar"""

    def compose(self) -> ComposeResult:
        text = Text()
        text.append("● ", style="bold red")
        text.append("wait ", style="dim")
        text.append("◐ ", style="bold yellow")
        text.append("think\n", style="dim")
        text.append("◑ ", style="bold cyan")
        text.append("work ", style="dim")
        text.append("○ ", style="dim")
        text.append("idle", style="dim")
        yield Static(text)




class CBOSApp(App):
    """CBOS - Claude Code Operating System TUI"""

    CSS = """
    Screen {
        background: $surface;
    }

    #main {
        layout: horizontal;
        height: 1fr;
    }

    #sidebar {
        width: 24;
        border: solid $primary;
        padding: 0 1;
    }

    #sidebar-title {
        text-align: center;
        text-style: bold;
        color: $text;
        padding: 1 0;
    }

    SessionList {
        height: 1fr;
    }

    SessionList > ListItem {
        padding: 0 1;
    }

    SessionList > ListItem.--highlight {
        background: $accent;
    }

    #status-legend {
        dock: bottom;
        height: 2;
        padding: 0 1;
    }

    #content {
        width: 1fr;
        border: solid $secondary;
    }

    #content-header {
        dock: top;
        height: 3;
        padding: 1;
        background: $surface-darken-1;
    }

    BufferView {
        height: 1fr;
        padding: 1;
    }

    #buffer-content {
        height: auto;
    }

    #question-highlight {
        height: auto;
        margin-top: 1;
    }

    #input-area {
        dock: bottom;
        height: auto;
        padding: 0 1;
        background: $surface-darken-1;
    }

    #input-field {
        height: 3;
    }

    #input-field:focus {
        border: tall $accent;
    }

    #suggestion-panel {
        dock: bottom;
        height: auto;
        max-height: 8;
        margin: 0 1;
    }

    #suggestion-content {
        height: auto;
    }

    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "create", "Create"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "suggest", "AI Suggest"),
        Binding("i", "focus_input", "Input", show=True),
        Binding("enter", "focus_input", "Input", show=False),
        Binding("escape", "focus_list", "Esc=cancel", show=True),
        Binding("ctrl+c", "interrupt", "Interrupt"),
        Binding("a", "attach", "Attach"),
    ]

    TITLE = "CBOS"
    SUB_TITLE = "Claude Code Session Manager"

    def __init__(self) -> None:
        super().__init__()
        self.sessions: list[dict] = []
        self.selected_slug: str | None = None
        self.current_suggestion: dict | None = None

        # Streaming state
        self._stream_buffers: dict[str, str] = {}  # session -> accumulated content
        self._ws_task: asyncio.Task | None = None
        self._ws_connected = False
        self._ws: websockets.WebSocketClientProtocol | None = None  # WebSocket connection
        self._pending_select_slug: str | None = None  # Session to auto-select after creation

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Label("Sessions", id="sidebar-title")
                yield Rule()
                yield SessionList(id="session-list")
                yield Rule()
                yield StatusLegend(id="status-legend")

            with Vertical(id="content"):
                yield Static("Select a session", id="content-header")
                yield SuggestionPanel(id="suggestion-panel")
                yield BufferView(id="buffer-view")
                with Vertical(id="input-area"):
                    yield Input(
                        placeholder="Type response here... (Enter=send, Esc=cancel)",
                        id="input-field",
                    )

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the app"""
        # Start WebSocket streaming connection
        self._ws_task = asyncio.create_task(self._stream_loop())
        # Session list comes from WebSocket on connect, no HTTP polling needed

    async def _stream_loop(self) -> None:
        """WebSocket streaming connection loop with reconnection"""
        while True:
            try:
                await self._connect_stream()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._ws_connected = False
                self._update_status_bar()
                self.notify(f"Stream disconnected: {e}", severity="warning", timeout=3)
                # Wait before reconnecting
                await asyncio.sleep(2)

    async def _connect_stream(self) -> None:
        """Connect to WebSocket stream and handle messages"""
        try:
            async with websockets.connect(WS_STREAM_URL) as ws:
                self._ws = ws
                self._ws_connected = True
                self._update_status_bar()
                self.notify("Stream connected", timeout=2)

                # Subscribe to all sessions
                await ws.send(json.dumps({
                    "type": "subscribe",
                    "sessions": ["*"]
                }))

                # Handle incoming messages
                async for message in ws:
                    try:
                        data = json.loads(message)
                        await self._handle_stream_message(data)
                    except json.JSONDecodeError:
                        pass

        except websockets.exceptions.ConnectionClosed:
            self._ws = None
            self._ws_connected = False
            self._update_status_bar()
        except Exception as e:
            self._ws = None
            self._ws_connected = False
            self._update_status_bar()
            raise

    async def _handle_stream_message(self, data: dict) -> None:
        """Handle a message from the WebSocket stream"""
        msg_type = data.get("type", "")

        if msg_type == "stream":
            # Real-time stream data
            session = data.get("session", "")
            content = data.get("data", "")
            is_snapshot = data.get("snapshot", False)

            if session and content:
                # Strip ANSI escape codes for clean display
                content = strip_ansi(content)

                if is_snapshot:
                    # Snapshot: replace buffer entirely
                    new_buffer = content
                else:
                    # Incremental: append to buffer
                    current = self._stream_buffers.get(session, "")
                    new_buffer = current + content

                # Trim to max size
                if len(new_buffer) > MAX_BUFFER_SIZE:
                    new_buffer = new_buffer[-MAX_BUFFER_SIZE:]

                self._stream_buffers[session] = new_buffer

                # Update display if this is the selected session
                if session == self.selected_slug:
                    self._update_buffer_from_stream(session)

        elif msg_type == "sessions":
            # Session list update
            sessions = data.get("sessions", [])
            if sessions:
                self._update_session_list(sessions)

        elif msg_type == "subscribed":
            # Subscription confirmation
            subscribed = data.get("sessions", [])
            self.notify(f"Subscribed to: {subscribed}", timeout=2)

    def _update_status_bar(self) -> None:
        """Update subtitle with connection status"""
        if self._ws_connected:
            self.sub_title = f"● streaming │ {get_version_string()}"
        else:
            self.sub_title = f"○ disconnected │ {get_version_string()}"

    def _update_buffer_from_stream(self, session: str) -> None:
        """Update the buffer view from streaming content"""
        buffer = self._stream_buffers.get(session, "")

        buffer_view = self.query_one("#buffer-view", BufferView)
        buffer_view.buffer = buffer
        # No question extraction in streaming mode
        buffer_view.question = ""

    def _update_session_list(self, new_sessions: list[dict]) -> None:
        """Update session list on main thread"""
        session_list = self.query_one("#session-list", SessionList)

        # Check if session list structure changed
        old_slugs = [s.get("slug") for s in self.sessions]
        new_slugs = [s.get("slug") for s in new_sessions]

        # Check for removed sessions (cleanup)
        removed_slugs = set(old_slugs) - set(new_slugs)
        for slug in removed_slugs:
            # Clear buffer for removed session
            self._stream_buffers.pop(slug, None)
            # Clear selection if this was the selected session
            if self.selected_slug == slug:
                self.selected_slug = None
                self.query_one("#content-header", Static).update("Select a session")
                self.query_one("#buffer-view", BufferView).buffer = ""

        self.sessions = new_sessions

        if old_slugs != new_slugs:
            # Structure changed, rebuild list
            current_index = session_list.index
            session_list.clear()

            for s in self.sessions:
                session_list.append(SessionItem(s))

            # Check if we need to auto-select a pending session
            if self._pending_select_slug:
                for i, s in enumerate(self.sessions):
                    if s.get("slug") == self._pending_select_slug:
                        session_list.index = i
                        # Trigger selection
                        self._select_session_by_slug(self._pending_select_slug)
                        self._pending_select_slug = None
                        break
            elif current_index is not None and 0 <= current_index < len(self.sessions):
                # Restore highlight
                session_list.index = current_index
        else:
            # Same structure, update items in place
            for i, (item, session) in enumerate(zip(session_list.children, self.sessions)):
                if isinstance(item, SessionItem):
                    # Update the session data
                    item.session = session
                    # Update the display
                    state = session.get("state", "unknown")
                    icon, style = STATE_STYLES.get(state, STATE_STYLES["unknown"])
                    slug = session.get("slug", "???")
                    text = Text()
                    text.append(icon, style=style)
                    text.append(slug, style="bold" if state == "waiting" else "")
                    # Find the Static widget inside and update it
                    static = item.query_one(Static)
                    static.update(text)

    def _select_session_by_slug(self, slug: str) -> None:
        """Select a session by its slug and update the UI"""
        # Find the session data
        session = None
        for s in self.sessions:
            if s.get("slug") == slug:
                session = s
                break

        if not session:
            return

        self.selected_slug = slug
        state = session.get("state", "unknown")
        icon, style = STATE_STYLES.get(state, STATE_STYLES["unknown"])

        # Update header
        header = self.query_one("#content-header", Static)
        header.update(
            Text.from_markup(
                f"[bold]{self.selected_slug}[/] [{style}]{icon}{state}[/]"
            )
        )

        # Show streaming buffer (may be empty if session just started)
        self._update_buffer_from_stream(self.selected_slug)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection"""
        if isinstance(event.item, SessionItem):
            slug = event.item.session.get("slug")
            self._select_session_by_slug(slug)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission"""
        text = event.value.strip()
        if not text or not self.selected_slug:
            return

        self.send_input(text)
        event.input.clear()
        self.query_one("#session-list", SessionList).focus()

    async def send_input_async(self, text: str) -> None:
        """Send input to the selected session via WebSocket"""
        if not self.selected_slug:
            return

        if self._ws and self._ws_connected:
            try:
                await self._ws.send(json.dumps({
                    "type": "send",
                    "session": self.selected_slug,
                    "text": text,
                }))
                self.notify(f"Sent to {self.selected_slug}", timeout=2)
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")
        else:
            self.notify("Not connected to stream", severity="warning")

    def send_input(self, text: str) -> None:
        """Send input to the selected session"""
        asyncio.create_task(self.send_input_async(text))

    def action_refresh(self) -> None:
        """Refresh sessions by reconnecting WebSocket"""
        if self._ws_task:
            self._ws_task.cancel()
        self._ws_task = asyncio.create_task(self._stream_loop())
        self.notify("Reconnecting stream...", timeout=2)

    def action_focus_input(self) -> None:
        """Focus the input field, optionally with suggestion"""
        input_field = self.query_one("#input-field", Input)

        # If we have an active suggestion, pre-fill the input
        if self.current_suggestion:
            response = self.current_suggestion.get("response", "")
            if response:
                input_field.value = response
            # Clear the suggestion panel
            self.query_one("#suggestion-panel", SuggestionPanel).clear()
            self.current_suggestion = None

        input_field.focus()

    def action_focus_list(self) -> None:
        """Focus the session list and clear suggestion"""
        self.query_one("#suggestion-panel", SuggestionPanel).clear()
        self.current_suggestion = None
        self.query_one("#session-list", SessionList).focus()

    @work(thread=True)
    def action_suggest(self) -> None:
        """Get AI suggestion for selected session"""
        if not self.selected_slug:
            self.call_from_thread(self.notify, "No session selected", severity="warning")
            return

        self.call_from_thread(self.notify, "Getting AI suggestion...", timeout=2)

        import httpx as sync_httpx

        try:
            with sync_httpx.Client(base_url=API_BASE, timeout=30) as client:
                resp = client.post(f"/sessions/{self.selected_slug}/suggest")
                resp.raise_for_status()
                data = resp.json()

                suggestion = data.get("suggestion", {})
                self.call_from_thread(self._show_suggestion, suggestion)

        except sync_httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                detail = e.response.json().get("detail", "Session not waiting")
                self.call_from_thread(self.notify, detail, severity="warning")
            else:
                self.call_from_thread(self.notify, f"Error: {e}", severity="error")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def _show_suggestion(self, suggestion: dict) -> None:
        """Show suggestion in the panel"""
        self.current_suggestion = suggestion
        panel = self.query_one("#suggestion-panel", SuggestionPanel)
        panel.suggestion = suggestion

        confidence = suggestion.get("confidence", 0)
        if confidence >= 0.7:
            self.notify("High confidence suggestion ready", timeout=2)
        else:
            self.notify("Suggestion ready (review recommended)", timeout=2)

    def action_interrupt(self) -> None:
        """Send interrupt to selected session via WebSocket"""
        if not self.selected_slug:
            self.notify("No session selected", severity="warning")
            return

        async def send_interrupt():
            if self._ws and self._ws_connected:
                try:
                    await self._ws.send(json.dumps({
                        "type": "interrupt",
                        "session": self.selected_slug,
                    }))
                    self.notify(f"Interrupted {self.selected_slug}", timeout=2)
                except Exception as e:
                    self.notify(f"Error: {e}", severity="error")
            else:
                self.notify("Not connected to stream", severity="warning")

        asyncio.create_task(send_interrupt())

    def action_attach(self) -> None:
        """Show attach command for selected session"""
        if not self.selected_slug:
            self.notify("No session selected", severity="warning")
            return

        cmd = f"screen -r {self.selected_slug}"
        self.notify(f"Run: {cmd}", timeout=5)

    @work(thread=True)
    def action_priority(self) -> None:
        """Show priority-ranked waiting sessions"""
        self.call_from_thread(self.notify, "Fetching priorities...", timeout=2)

        import httpx as sync_httpx

        try:
            with sync_httpx.Client(base_url=API_BASE, timeout=30) as client:
                resp = client.get("/sessions/prioritized")
                resp.raise_for_status()
                prioritized = resp.json()

                if not prioritized:
                    self.call_from_thread(self.notify, "No sessions waiting", severity="warning")
                    return

                # Format priority list
                lines = ["Priority Queue:"]
                for i, p in enumerate(prioritized[:5], 1):
                    score = p.get("priority", {}).get("score", 0)
                    reason = p.get("priority", {}).get("reason", "")
                    slug = p.get("slug", "???")
                    lines.append(f"  {i}. [{score:.0%}] {slug} - {reason}")

                self.call_from_thread(self.notify, "\n".join(lines), timeout=10)

        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    @work(thread=True)
    def action_related(self) -> None:
        """Find sessions related to the selected one"""
        if not self.selected_slug:
            self.call_from_thread(self.notify, "No session selected", severity="warning")
            return

        self.call_from_thread(self.notify, "Finding related sessions...", timeout=2)

        import httpx as sync_httpx

        try:
            with sync_httpx.Client(base_url=API_BASE, timeout=30) as client:
                resp = client.get(f"/sessions/{self.selected_slug}/related")
                resp.raise_for_status()
                related = resp.json()

                if not related:
                    self.call_from_thread(
                        self.notify,
                        f"No sessions related to {self.selected_slug}",
                        timeout=3
                    )
                    return

                # Format related list
                lines = [f"Sessions related to {self.selected_slug}:"]
                for r in related[:5]:
                    similarity = r.get("similarity", 0)
                    slug = r.get("slug", "???")
                    topics = ", ".join(r.get("shared_topics", [])[:3]) or "various"
                    lines.append(f"  [{similarity:.0%}] {slug} ({topics})")

                self.call_from_thread(self.notify, "\n".join(lines), timeout=10)

        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def action_create(self) -> None:
        """Open create session dialog"""
        self.notify("Discovering Claude projects...", timeout=2)

        # Get active session paths to filter out
        active_paths = set()
        for session in self.sessions:
            path = session.get("path", "")
            if path:
                active_paths.add(path)

        # Discover projects in background thread
        self._discover_and_show_create_dialog(active_paths)

    @work(thread=True)
    def _discover_and_show_create_dialog(self, active_paths: set[str]) -> None:
        """Discover projects and show create dialog"""
        projects = discover_claude_projects(active_paths)

        if not projects:
            self.call_from_thread(
                self.notify,
                "No Claude projects found (looking for CLAUDE.md files)",
                severity="warning",
                timeout=5
            )
            return

        # Show the modal on main thread
        self.call_from_thread(self._show_create_dialog, projects)

    def _show_create_dialog(self, projects: list[dict]) -> None:
        """Show the create session dialog"""
        def handle_result(result: dict | None) -> None:
            if result:
                self._create_session(result)

        self.push_screen(CreateSessionScreen(projects), handle_result)

    @work(thread=True)
    def _create_session(self, project: dict) -> None:
        """Create a new session via API"""
        import httpx as sync_httpx

        slug = project["name"]
        path = project["path"]

        self.call_from_thread(
            self.notify,
            f"Creating session {slug}...",
            timeout=2
        )

        try:
            with sync_httpx.Client(base_url=API_BASE, timeout=30) as client:
                resp = client.post(
                    "/sessions",
                    json={"slug": slug, "path": path}
                )
                resp.raise_for_status()

                self.call_from_thread(
                    self.notify,
                    f"Created session: {slug}",
                    timeout=3
                )

                # Store slug to auto-select after refresh
                self._pending_select_slug = slug

                # Reconnect WebSocket to get updated session list
                self.call_from_thread(self.action_refresh)

        except sync_httpx.HTTPStatusError as e:
            detail = "Unknown error"
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            self.call_from_thread(
                self.notify,
                f"Failed to create session: {detail}",
                severity="error",
                timeout=5
            )
        except Exception as e:
            self.call_from_thread(
                self.notify,
                f"Error: {e}",
                severity="error"
            )


def main() -> None:
    """Entry point for cbos command"""
    app = CBOSApp()
    app.run()


if __name__ == "__main__":
    main()
