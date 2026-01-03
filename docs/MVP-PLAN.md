# CBOS - Claude Code Operating System

## MVP Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         TUI (Textual)                           │
│  ┌──────────────┐ ┌─────────────────────┐ ┌──────────────────┐  │
│  │ Session List │ │   Context Preview   │ │   Input Panel    │  │
│  │              │ │                     │ │                  │  │
│  │ ● AUTH  wait │ │ Last 20 lines of    │ │ > Type response  │  │
│  │ ○ INTEL work │ │ selected session    │ │   or /command    │  │
│  │ ◐ DOCS think │ │ buffer with Claude  │ │                  │  │
│  │ ○ APP   idle │ │ question highlighted│ │ [Send] [Stash]   │  │
│  └──────────────┘ └─────────────────────┘ └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ WebSocket + REST
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Server                             │
│  /sessions          - CRUD for sessions                         │
│  /sessions/{id}/send - Send input to session                    │
│  /sessions/{id}/buffer - Get current buffer                     │
│  /stash             - Manage stashed responses                  │
│  /ws                - Real-time status updates                  │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Screen Manager Library                       │
│  - launch_session(slug, path)                                   │
│  - kill_session(slug)                                           │
│  - capture_buffer(slug) -> str                                  │
│  - send_input(slug, text)                                       │
│  - list_sessions() -> List[ScreenSession]                       │
│  - detect_state(buffer) -> SessionState                         │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     GNU Screen Sessions                         │
│  AUTH | INTEL | DOCS | APP | MODELS | TENANT | ...              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Core Library (`cbos/core/`)

### 1.1 Models (`models.py`)

```python
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class SessionState(str, Enum):
    WAITING = "waiting"      # Claude waiting for user input (> prompt visible)
    THINKING = "thinking"    # Claude is processing (● spinner)
    WORKING = "working"      # Claude executing tools
    IDLE = "idle"            # Session idle, no recent activity
    ERROR = "error"          # Session in error state
    UNKNOWN = "unknown"      # Cannot determine state

class Session(BaseModel):
    slug: str                           # e.g., "AUTH", "INTEL"
    path: str                           # Working directory
    screen_id: str                      # e.g., "900379.AUTH"
    state: SessionState = SessionState.UNKNOWN
    pid: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)
    last_question: Optional[str] = None # Last question Claude asked (if waiting)
    buffer_tail: Optional[str] = None   # Last N lines of buffer

class StashedResponse(BaseModel):
    id: str                             # UUID
    session_slug: str
    question: str                       # What Claude asked
    response: str                       # User's stashed response
    created_at: datetime = Field(default_factory=datetime.now)
    applied: bool = False

class SessionCreate(BaseModel):
    slug: str
    path: str

class SendInput(BaseModel):
    text: str
```

### 1.2 Screen Manager (`screen.py`)

```python
import subprocess
import re
from pathlib import Path
from typing import Optional
from .models import Session, SessionState

class ScreenManager:
    def __init__(self, log_dir: Path = Path.home() / "claude_logs"):
        self.log_dir = log_dir
        self.log_dir.mkdir(exist_ok=True)

    def list_sessions(self) -> list[tuple[str, str, bool]]:
        """Returns list of (pid.name, name, attached)"""
        result = subprocess.run(
            ["screen", "-ls"],
            capture_output=True, text=True
        )
        # Parse: 900379.AUTH (01/01/2026 09:00:39 PM) (Attached)
        pattern = r'(\d+)\.(\S+)\s+\([^)]+\)\s+\((Attached|Detached)\)'
        return [
            (f"{m.group(1)}.{m.group(2)}", m.group(2), m.group(3) == "Attached")
            for m in re.finditer(pattern, result.stdout)
        ]

    def launch(self, slug: str, path: str) -> str:
        """Launch a new Claude Code session, returns screen_id"""
        logfile = self.log_dir / f"{slug}.log"
        cmd = [
            "screen", "-dmS", slug, "-L", "-Logfile", str(logfile),
            "bash", "-c", f"cd '{path}' && NO_COLOR=1 claude"
        ]
        subprocess.run(cmd, check=True)
        # Get the new session ID
        for screen_id, name, _ in self.list_sessions():
            if name == slug:
                return screen_id
        raise RuntimeError(f"Failed to find launched session {slug}")

    def kill(self, slug: str) -> bool:
        """Kill a screen session"""
        result = subprocess.run(
            ["screen", "-S", slug, "-X", "quit"],
            capture_output=True
        )
        return result.returncode == 0

    def capture_buffer(self, slug: str, tail_lines: int = 100) -> str:
        """Capture the scrollback buffer"""
        tmp = Path(f"/tmp/cbos_{slug}.txt")
        subprocess.run(
            ["screen", "-S", slug, "-X", "hardcopy", "-h", str(tmp)],
            check=True
        )
        content = tmp.read_text()
        # Strip ANSI codes
        content = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', content)
        # Return last N lines
        lines = content.strip().split('\n')
        return '\n'.join(lines[-tail_lines:])

    def send_input(self, slug: str, text: str) -> bool:
        """Send keystrokes to a session"""
        # Escape special characters and add newline
        escaped = text.replace("'", "'\\''")
        result = subprocess.run(
            ["screen", "-S", slug, "-X", "stuff", f"{escaped}\n"],
            capture_output=True
        )
        return result.returncode == 0

    def detect_state(self, buffer: str) -> tuple[SessionState, Optional[str]]:
        """
        Detect Claude Code state from buffer.
        Returns (state, last_question_if_waiting)
        """
        lines = buffer.strip().split('\n')
        if not lines:
            return SessionState.UNKNOWN, None

        # Check last few lines for patterns
        tail = '\n'.join(lines[-10:])

        # Waiting for input: line ends with > or has empty > prompt
        if re.search(r'^>\s*$', lines[-1]) or lines[-1].strip() == '>':
            # Look back for the question
            question = self._extract_last_question(lines)
            return SessionState.WAITING, question

        # Thinking: has spinner character
        if '●' in tail or '◐' in tail or '◑' in tail:
            return SessionState.THINKING, None

        # Working: tool execution patterns
        if re.search(r'(Bash|Read|Write|Edit|Grep|Glob)\(', tail):
            return SessionState.WORKING, None

        # Error patterns
        if 'Error:' in tail or 'error:' in tail:
            return SessionState.ERROR, None

        # Idle if nothing recent
        return SessionState.IDLE, None

    def _extract_last_question(self, lines: list[str]) -> Optional[str]:
        """Extract the last question Claude asked before the prompt"""
        # Look for Claude's output before the > prompt
        question_lines = []
        for line in reversed(lines[:-1]):
            if line.strip().startswith('>'):
                break
            if line.strip():
                question_lines.insert(0, line.strip())
            if len(question_lines) > 5:
                break
        return '\n'.join(question_lines) if question_lines else None
```

### 1.3 Session Store (`store.py`)

```python
from pathlib import Path
import json
from datetime import datetime
from typing import Optional
from .models import Session, StashedResponse, SessionState
from .screen import ScreenManager

class SessionStore:
    """In-memory session store with JSON persistence"""

    def __init__(self, persist_path: Path = Path.home() / ".cbos/sessions.json"):
        self.persist_path = persist_path
        self.persist_path.parent.mkdir(exist_ok=True)
        self.screen = ScreenManager()
        self._sessions: dict[str, Session] = {}
        self._stash: dict[str, StashedResponse] = {}
        self._load()

    def _load(self):
        if self.persist_path.exists():
            data = json.loads(self.persist_path.read_text())
            # Reconstruct from saved data
            for s in data.get("sessions", []):
                self._sessions[s["slug"]] = Session(**s)

    def _save(self):
        data = {
            "sessions": [s.model_dump(mode="json") for s in self._sessions.values()],
            "stash": [r.model_dump(mode="json") for r in self._stash.values()]
        }
        self.persist_path.write_text(json.dumps(data, indent=2, default=str))

    def sync_with_screen(self) -> list[Session]:
        """Sync stored sessions with actual screen sessions"""
        screen_sessions = {name: (sid, attached)
                          for sid, name, attached in self.screen.list_sessions()}

        # Update existing, remove dead
        for slug in list(self._sessions.keys()):
            if slug not in screen_sessions:
                del self._sessions[slug]
            else:
                session = self._sessions[slug]
                session.screen_id = screen_sessions[slug][0]

        # Discover new (from screen but not in store)
        for slug, (screen_id, _) in screen_sessions.items():
            if slug not in self._sessions:
                # New session discovered
                self._sessions[slug] = Session(
                    slug=slug,
                    path="",  # Unknown, user can update
                    screen_id=screen_id
                )

        self._save()
        return list(self._sessions.values())

    def refresh_states(self):
        """Update state for all sessions by reading buffers"""
        for session in self._sessions.values():
            try:
                buffer = self.screen.capture_buffer(session.slug)
                session.buffer_tail = buffer
                state, question = self.screen.detect_state(buffer)
                session.state = state
                session.last_question = question
                session.last_activity = datetime.now()
            except Exception:
                session.state = SessionState.ERROR
        self._save()

    def get(self, slug: str) -> Optional[Session]:
        return self._sessions.get(slug)

    def all(self) -> list[Session]:
        return list(self._sessions.values())

    def create(self, slug: str, path: str) -> Session:
        screen_id = self.screen.launch(slug, path)
        session = Session(slug=slug, path=path, screen_id=screen_id)
        self._sessions[slug] = session
        self._save()
        return session

    def delete(self, slug: str) -> bool:
        if slug in self._sessions:
            self.screen.kill(slug)
            del self._sessions[slug]
            self._save()
            return True
        return False

    def send_input(self, slug: str, text: str) -> bool:
        if slug in self._sessions:
            return self.screen.send_input(slug, text)
        return False
```

---

## Phase 2: FastAPI Server (`cbos/api/`)

### 2.1 Main App (`main.py`)

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from ..core.store import SessionStore
from ..core.models import Session, SessionCreate, SendInput

store: SessionStore = None
connected_clients: set[WebSocket] = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global store
    store = SessionStore()
    store.sync_with_screen()
    # Start background refresh task
    task = asyncio.create_task(refresh_loop())
    yield
    task.cancel()

app = FastAPI(title="CBOS API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

async def refresh_loop():
    """Periodically refresh session states and notify clients"""
    while True:
        await asyncio.sleep(2)  # Poll every 2 seconds
        store.sync_with_screen()
        store.refresh_states()
        # Notify WebSocket clients
        data = {"type": "refresh", "sessions": [s.model_dump(mode="json") for s in store.all()]}
        for ws in list(connected_clients):
            try:
                await ws.send_json(data)
            except:
                connected_clients.discard(ws)

# REST Endpoints
@app.get("/sessions", response_model=list[Session])
def list_sessions():
    store.sync_with_screen()
    store.refresh_states()
    return store.all()

@app.get("/sessions/{slug}", response_model=Session)
def get_session(slug: str):
    session = store.get(slug)
    if not session:
        raise HTTPException(404, "Session not found")
    return session

@app.post("/sessions", response_model=Session)
def create_session(req: SessionCreate):
    return store.create(req.slug, req.path)

@app.delete("/sessions/{slug}")
def delete_session(slug: str):
    if not store.delete(slug):
        raise HTTPException(404, "Session not found")
    return {"status": "deleted"}

@app.post("/sessions/{slug}/send")
def send_to_session(slug: str, req: SendInput):
    if not store.send_input(slug, req.text):
        raise HTTPException(400, "Failed to send input")
    return {"status": "sent"}

@app.get("/sessions/{slug}/buffer")
def get_buffer(slug: str, lines: int = 100):
    session = store.get(slug)
    if not session:
        raise HTTPException(404, "Session not found")
    buffer = store.screen.capture_buffer(slug, lines)
    return {"buffer": buffer}

# WebSocket for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    try:
        # Send initial state
        await ws.send_json({
            "type": "init",
            "sessions": [s.model_dump(mode="json") for s in store.all()]
        })
        # Keep connection alive
        while True:
            # Listen for client messages (e.g., send input)
            data = await ws.receive_json()
            if data.get("type") == "send":
                store.send_input(data["slug"], data["text"])
    except WebSocketDisconnect:
        connected_clients.discard(ws)
```

### 2.2 Service File (`/etc/systemd/system/cbos.service`)

```ini
[Unit]
Description=CBOS - Claude Code Session Manager
After=network.target

[Service]
Type=simple
User=bisenbek
WorkingDirectory=/home/bisenbek/projects/nominate/cbos
Environment="PATH=/home/bisenbek/.pyenv/versions/nominates/bin"
ExecStart=/home/bisenbek/.pyenv/versions/nominates/bin/uvicorn cbos.api.main:app --host 127.0.0.1 --port 8901
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

---

## Phase 3: TUI (`cbos/tui/`)

### 3.1 Main App (`app.py`)

```python
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, ListView, ListItem, Input
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual import work
import httpx

class SessionItem(ListItem):
    def __init__(self, session: dict):
        super().__init__()
        self.session = session

    def compose(self):
        state_icons = {
            "waiting": "● ",   # Red/attention
            "thinking": "◐ ",  # Yellow/processing
            "working": "◑ ",   # Blue/active
            "idle": "○ ",      # Gray/idle
            "error": "✗ ",     # Red/error
            "unknown": "? "
        }
        icon = state_icons.get(self.session["state"], "? ")
        yield Static(f"{icon}{self.session['slug']}")

class BufferView(Static):
    buffer = reactive("")

    def watch_buffer(self, value: str):
        self.update(value)

class CBOSApp(App):
    CSS = """
    #main { layout: horizontal; }
    #session-list { width: 20; border: solid green; }
    #buffer-view { width: 1fr; border: solid blue; }
    #input-panel { height: 3; dock: bottom; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("s", "send", "Send Input"),
        ("/", "command", "Command"),
    ]

    def __init__(self):
        super().__init__()
        self.sessions = []
        self.selected_slug = None
        self.client = httpx.AsyncClient(base_url="http://127.0.0.1:8901")

    def compose(self) -> ComposeResult:
        yield Header(name="CBOS")
        with Horizontal(id="main"):
            yield ListView(id="session-list")
            yield BufferView(id="buffer-view")
        yield Input(placeholder="Type response or /command...", id="input-panel")
        yield Footer()

    async def on_mount(self):
        await self.refresh_sessions()
        self.set_interval(2, self.refresh_sessions)

    @work
    async def refresh_sessions(self):
        try:
            resp = await self.client.get("/sessions")
            self.sessions = resp.json()
            session_list = self.query_one("#session-list", ListView)
            session_list.clear()
            for s in self.sessions:
                session_list.append(SessionItem(s))
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    async def on_list_view_selected(self, event: ListView.Selected):
        if isinstance(event.item, SessionItem):
            self.selected_slug = event.item.session["slug"]
            await self.load_buffer()

    @work
    async def load_buffer(self):
        if not self.selected_slug:
            return
        try:
            resp = await self.client.get(f"/sessions/{self.selected_slug}/buffer")
            buffer_view = self.query_one("#buffer-view", BufferView)
            buffer_view.buffer = resp.json()["buffer"]
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    async def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text or not self.selected_slug:
            return

        if text.startswith("/"):
            await self.handle_command(text)
        else:
            await self.send_input(text)

        event.input.clear()

    @work
    async def send_input(self, text: str):
        try:
            await self.client.post(
                f"/sessions/{self.selected_slug}/send",
                json={"text": text}
            )
            self.notify(f"Sent to {self.selected_slug}")
            await self.load_buffer()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    async def handle_command(self, cmd: str):
        if cmd == "/status":
            waiting = [s["slug"] for s in self.sessions if s["state"] == "waiting"]
            self.notify(f"Waiting: {', '.join(waiting) or 'None'}")
        elif cmd == "/refresh":
            await self.refresh_sessions()

def main():
    app = CBOSApp()
    app.run()

if __name__ == "__main__":
    main()
```

---

## Directory Structure

```
cbos/
├── docs/
│   ├── START-HERE.md          # Existing
│   └── MVP-PLAN.md            # This document
├── cbos/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py          # Pydantic models
│   │   ├── screen.py          # Screen manager
│   │   └── store.py           # Session store
│   ├── api/
│   │   ├── __init__.py
│   │   └── main.py            # FastAPI app
│   └── tui/
│       ├── __init__.py
│       └── app.py             # Textual TUI
├── tests/
│   ├── __init__.py
│   ├── test_screen.py
│   ├── test_store.py
│   └── test_api.py
├── pyproject.toml
└── README.md
```

---

## Implementation Order

### Sprint 1: Core Library
1. [ ] Create project structure and `pyproject.toml`
2. [ ] Implement `models.py` with Pydantic models
3. [ ] Implement `screen.py` - Screen manager (list, launch, kill, capture, send)
4. [ ] Implement state detection (parse buffer for waiting/thinking/working)
5. [ ] Implement `store.py` - Session store with sync
6. [ ] Write tests for screen manager and store

### Sprint 2: FastAPI Server
7. [ ] Implement `api/main.py` with REST endpoints
8. [ ] Add WebSocket support for real-time updates
9. [ ] Create systemd service file
10. [ ] Write API tests
11. [ ] Deploy and test with real sessions

### Sprint 3: TUI
12. [ ] Implement basic TUI layout with Textual
13. [ ] Add session list with state indicators
14. [ ] Add buffer preview panel
15. [ ] Add input panel with send capability
16. [ ] Add keyboard shortcuts
17. [ ] Polish styling (Claude Code vibes - green/blue theme)

### Sprint 4: Polish
18. [ ] Add stash functionality (save responses for later)
19. [ ] Add notifications/alerts for waiting sessions
20. [ ] Add session creation from TUI
21. [ ] Error handling and edge cases
22. [ ] Documentation

---

## Claude Code State Detection Patterns

From buffer analysis:

| State | Detection Pattern |
|-------|-------------------|
| WAITING | Last line is `>` or `> ` (empty prompt) |
| THINKING | Buffer contains `●`, `◐`, `◑` spinners |
| WORKING | Lines contain `Bash(`, `Read(`, `Edit(`, etc. |
| IDLE | No recent activity patterns |
| ERROR | Contains `Error:` or `error:` |

---

## Commands

```bash
# Development
source ~/.pyenv/versions/nominates/bin/activate
cd ~/projects/nominate/cbos

# Run API in dev mode
uvicorn cbos.api.main:app --reload --port 8901

# Run TUI
python -m cbos.tui.app

# Run tests
pytest tests/

# Install as service
sudo cp cbos.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cbos
sudo systemctl start cbos
```
