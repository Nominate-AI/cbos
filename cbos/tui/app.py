"""CBOS TUI - Claude Code Session Manager"""

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import (
    Header,
    Footer,
    Static,
    ListView,
    ListItem,
    Input,
    Label,
    Rule,
)
from textual import work
from rich.text import Text
from rich.panel import Panel

API_BASE = "http://127.0.0.1:32205"


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
        yield Static(id="buffer-content")
        yield Static(id="question-highlight")

    def watch_buffer(self, value: str) -> None:
        content = self.query_one("#buffer-content", Static)
        # Show last 100 lines, don't strip trailing whitespace
        lines = value.split("\n")[-100:]
        content.update("\n".join(lines))

    def watch_question(self, value: str) -> None:
        highlight = self.query_one("#question-highlight", Static)
        if value:
            highlight.update(
                Panel(value, title="[bold yellow]Waiting for response[/]", border_style="yellow")
            )
        else:
            highlight.update("")


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
        height: 5;
        padding: 1;
        background: $surface-darken-1;
    }

    #input-field {
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "focus_input", "Send", show=True),
        Binding("i", "focus_input", "Input", show=False),
        Binding("escape", "focus_list", "Back", show=False),
        Binding("ctrl+c", "interrupt", "Interrupt"),
        Binding("a", "attach", "Attach"),
    ]

    TITLE = "CBOS"
    SUB_TITLE = "Claude Code Session Manager"

    def __init__(self) -> None:
        super().__init__()
        self.sessions: list[dict] = []
        self.selected_slug: str | None = None
        self.client = httpx.AsyncClient(base_url=API_BASE, timeout=10)

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
                yield BufferView(id="buffer-view")
                with Vertical(id="input-area"):
                    yield Label("Response (Enter to send, Esc to cancel):")
                    yield Input(
                        placeholder="Type your response...",
                        id="input-field",
                    )

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the app"""
        self.refresh_sessions()
        self.set_interval(3, self.refresh_sessions)

    @work(exclusive=True, thread=True)
    def refresh_sessions(self) -> None:
        """Refresh session list from API"""
        import httpx as sync_httpx

        try:
            with sync_httpx.Client(base_url=API_BASE, timeout=10) as client:
                resp = client.get("/sessions")
                resp.raise_for_status()
                new_sessions = resp.json()

                # Call UI updates on main thread
                self.call_from_thread(self._update_session_list, new_sessions)

                # Get status
                status_resp = client.get("/sessions/status")
                status = status_resp.json()
                self.call_from_thread(self._update_status, status)

        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error", timeout=5)

    def _update_session_list(self, new_sessions: list[dict]) -> None:
        """Update session list on main thread"""
        session_list = self.query_one("#session-list", SessionList)

        # Check if session list structure changed
        old_slugs = [s.get("slug") for s in self.sessions]
        new_slugs = [s.get("slug") for s in new_sessions]

        self.sessions = new_sessions

        if old_slugs != new_slugs:
            # Structure changed, rebuild list
            current_index = session_list.index
            session_list.clear()

            for s in self.sessions:
                session_list.append(SessionItem(s))

            # Restore highlight
            if current_index is not None and 0 <= current_index < len(self.sessions):
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

    def _update_status(self, status: dict) -> None:
        """Update status display"""
        # Status is now shown in sidebar legend, could add counts to header if needed
        pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection"""
        if isinstance(event.item, SessionItem):
            self.selected_slug = event.item.session.get("slug")
            self.load_buffer()

    @work(exclusive=True, thread=True)
    def load_buffer(self) -> None:
        """Load buffer for selected session"""
        if not self.selected_slug:
            return

        import httpx as sync_httpx

        try:
            with sync_httpx.Client(base_url=API_BASE, timeout=10) as client:
                # Get session details
                resp = client.get(f"/sessions/{self.selected_slug}")
                resp.raise_for_status()
                session = resp.json()

                # Get buffer
                buf_resp = client.get(
                    f"/sessions/{self.selected_slug}/buffer",
                    params={"lines": 100},
                )
                buf_resp.raise_for_status()
                buffer_data = buf_resp.json()

                # Update UI on main thread
                self.call_from_thread(
                    self._update_buffer_view,
                    session,
                    buffer_data.get("buffer", "")
                )

        except Exception as e:
            self.call_from_thread(self.notify, f"Error loading buffer: {e}", severity="error")

    def _update_buffer_view(self, session: dict, buffer: str) -> None:
        """Update buffer view on main thread"""
        state = session.get("state", "unknown")
        icon, style = STATE_STYLES.get(state, STATE_STYLES["unknown"])

        header = self.query_one("#content-header", Static)
        header.update(
            Text.from_markup(
                f"[bold]{self.selected_slug}[/] [{style}]{icon}{state}[/]"
            )
        )

        buffer_view = self.query_one("#buffer-view", BufferView)
        buffer_view.buffer = buffer
        buffer_view.question = session.get("last_question", "") or ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission"""
        text = event.value.strip()
        if not text or not self.selected_slug:
            return

        self.send_input(text)
        event.input.clear()
        self.query_one("#session-list", SessionList).focus()

    @work(thread=True)
    def send_input(self, text: str) -> None:
        """Send input to the selected session"""
        if not self.selected_slug:
            return

        import httpx as sync_httpx

        try:
            with sync_httpx.Client(base_url=API_BASE, timeout=10) as client:
                resp = client.post(
                    f"/sessions/{self.selected_slug}/send",
                    json={"text": text},
                )
                resp.raise_for_status()
                self.call_from_thread(self.notify, f"Sent to {self.selected_slug}", timeout=2)

        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def action_refresh(self) -> None:
        """Refresh sessions"""
        self.refresh_sessions()

    def action_focus_input(self) -> None:
        """Focus the input field"""
        self.query_one("#input-field", Input).focus()

    def action_focus_list(self) -> None:
        """Focus the session list"""
        self.query_one("#session-list", SessionList).focus()

    @work(thread=True)
    def action_interrupt(self) -> None:
        """Send interrupt to selected session"""
        if not self.selected_slug:
            self.call_from_thread(self.notify, "No session selected", severity="warning")
            return

        import httpx as sync_httpx

        try:
            with sync_httpx.Client(base_url=API_BASE, timeout=10) as client:
                resp = client.post(f"/sessions/{self.selected_slug}/interrupt")
                resp.raise_for_status()
                self.call_from_thread(self.notify, f"Interrupted {self.selected_slug}", timeout=2)
        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def action_attach(self) -> None:
        """Show attach command for selected session"""
        if not self.selected_slug:
            self.notify("No session selected", severity="warning")
            return

        cmd = f"screen -r {self.selected_slug}"
        self.notify(f"Run: {cmd}", timeout=5)


def main() -> None:
    """Entry point for cbos command"""
    app = CBOSApp()
    app.run()


if __name__ == "__main__":
    main()
