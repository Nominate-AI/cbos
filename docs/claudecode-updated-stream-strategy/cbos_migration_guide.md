# CBOS Migration Guide: Screen Scraping → JSON Streaming

## Overview

This guide shows how to integrate JSON-mode sessions into your existing CBOS architecture alongside the current screen-based sessions.

## Step 1: Test JSON Output on Your System

First, verify that `--output-format stream-json` works:

```bash
# Basic test
claude -p "Hello, what can you do?" --output-format stream-json

# With resume capability
SESSION_ID=$(claude -p "What's 2+2?" --output-format stream-json 2>&1 | \
    grep '"type":"init"' | jq -r '.session_id')

# Continue the same conversation
claude -p "And what's that times 3?" --output-format stream-json --resume "$SESSION_ID"
```

You should see output like:
```json
{"type":"init","session_id":"abc123","cwd":"/home/user"}
{"type":"assistant","message":{"content":"Hello! I can help you..."}}
{"type":"result","subtype":"success","cost_usd":0.001}
```

## Step 2: Add JSON Session Support to CBOS

### 2.1 Create `cbos/core/json_manager.py`

Copy the `json_session_manager.py` file I provided and integrate it:

```python
# cbos/core/json_manager.py

from .json_session_manager import (
    JSONSessionManager,
    JSONSession,
    SessionState,
    ClaudeEvent,
)

__all__ = [
    "JSONSessionManager",
    "JSONSession", 
    "SessionState",
    "ClaudeEvent",
]
```

### 2.2 Add New Endpoints to `cbos/api/main.py`

```python
from ..core.json_manager import JSONSessionManager, SessionState as JSONState

# Global JSON session manager
json_manager: Optional[JSONSessionManager] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, stream_manager, json_manager
    # ... existing initialization ...
    
    # Initialize JSON session manager
    config = get_config()
    json_manager = JSONSessionManager(
        claude_command=config.claude_command,
        env_vars={"MAX_THINKING_TOKENS": "32000"}  # Optional
    )
    
    # Register callback to broadcast JSON events via WebSocket
    async def broadcast_json_event(slug: str, event):
        await connection_manager.broadcast_json_event(slug, event)
    json_manager.on_event(broadcast_json_event)
    
    yield
    # ... existing cleanup ...


# =============================================================================
# JSON Session Endpoints
# =============================================================================

@app.post("/json-sessions", response_model=dict)
def create_json_session(req: SessionCreate):
    """Create a new JSON-mode Claude session"""
    try:
        session = json_manager.create_session(req.slug, req.path)
        return session.to_dict()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/json-sessions/{slug}")
def get_json_session(slug: str):
    """Get JSON session details"""
    session = json_manager.get_session(slug)
    if not session:
        raise HTTPException(404, f"JSON session '{slug}' not found")
    return session.to_dict()


@app.post("/json-sessions/{slug}/invoke")
async def invoke_json_session(slug: str, prompt: str):
    """
    Invoke Claude on a JSON session.
    
    This is async - events are streamed via WebSocket.
    Returns immediately with invocation status.
    """
    session = json_manager.get_session(slug)
    if not session:
        raise HTTPException(404, f"JSON session '{slug}' not found")
    
    if session.state == JSONState.RUNNING:
        raise HTTPException(400, f"Session '{slug}' is already running")
    
    # Start invocation in background
    async def run_invocation():
        async for event in json_manager.invoke(slug, prompt):
            pass  # Events are broadcast via callback
    
    asyncio.create_task(run_invocation())
    
    return {"status": "started", "slug": slug}


@app.get("/json-sessions/{slug}/events")
def get_json_events(slug: str, limit: int = 50, event_type: Optional[str] = None):
    """Get recent events for a JSON session"""
    events = json_manager.get_events(slug, limit=limit, event_type=event_type)
    return {"events": [e.to_dict() for e in events]}


@app.post("/json-sessions/{slug}/interrupt")
async def interrupt_json_session(slug: str):
    """Interrupt a running JSON session"""
    if await json_manager.interrupt(slug):
        return {"status": "interrupted", "slug": slug}
    raise HTTPException(400, "Session not running or not found")
```

### 2.3 Update WebSocket Handler

```python
# In cbos/api/websocket.py

async def broadcast_json_event(self, slug: str, event) -> None:
    """Broadcast a JSON Claude event to subscribed clients"""
    message = {
        "type": "claude_event",
        "session": slug,
        "event": event.to_dict(),
        "ts": time.time(),
    }
    
    # Similar to broadcast_stream, but filter by subscription
    # ...


# In /ws/stream handler, add support for JSON session messages:

elif msg_type == "invoke":
    # Client wants to send prompt to JSON session
    session_slug = data.get("session")
    prompt = data.get("prompt")
    
    if session_slug and prompt:
        # Check if this is a JSON session
        json_session = json_manager.get_session(session_slug)
        if json_session:
            # Start invocation (events will be broadcast)
            asyncio.create_task(
                self._invoke_json_session(session_slug, prompt)
            )
            await ws.send_json({
                "type": "invoke_started",
                "session": session_slug,
            })
        else:
            # Fall back to screen-based session
            success = store.send_input(session_slug, prompt)
            await ws.send_json({
                "type": "send_result",
                "session": session_slug,
                "success": success,
            })
```

### 2.4 Update TUI to Handle JSON Events

```python
# In cbos/tui/app.py

async def _handle_stream_message(self, data: dict) -> None:
    msg_type = data.get("type", "")
    
    # ... existing handlers ...
    
    elif msg_type == "claude_event":
        # JSON session event
        session = data.get("session", "")
        event = data.get("event", {})
        
        # Format the event for display
        formatted = self._format_claude_event(event)
        
        if session in self._stream_buffers:
            self._stream_buffers[session] += formatted
            if session == self.selected_slug:
                self._update_buffer_from_stream(session)

def _format_claude_event(self, event: dict) -> str:
    """Format a Claude JSON event for display"""
    event_type = event.get("type", "")
    data = event.get("data", {})
    
    if event_type == "assistant":
        message = data.get("message", {})
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        return f"\n{content}\n"
    
    elif event_type == "tool_use":
        tool = data.get("tool", {})
        name = tool.get("name", "unknown")
        return f"\n◐ {name}(...)\n"
    
    elif event_type == "tool_result":
        return f"✓ Tool completed\n"
    
    elif event_type == "result":
        cost = data.get("cost_usd", 0)
        return f"\n[Cost: ${cost:.4f}]\n"
    
    else:
        return f"\n[{event_type}]\n"
```

## Step 3: Session Type Selection

Add a way to choose between screen-based and JSON-based sessions:

```python
# cbos/core/models.py

class SessionType(str, Enum):
    SCREEN = "screen"  # Traditional screen-based session
    JSON = "json"      # JSON streaming mode


# Update SessionCreate
class SessionCreate(BaseModel):
    slug: str
    path: str
    session_type: SessionType = SessionType.SCREEN  # Default to existing behavior
```

## Step 4: Unified Session View

Create a unified interface that works with both session types:

```python
# cbos/core/unified.py

class UnifiedSession:
    """Unified view of either screen or JSON sessions"""
    
    @classmethod
    def from_screen(cls, session: Session) -> "UnifiedSession":
        return cls(
            slug=session.slug,
            path=session.path,
            session_type=SessionType.SCREEN,
            state=session.state.value,
            # ...
        )
    
    @classmethod
    def from_json(cls, session: JSONSession) -> "UnifiedSession":
        return cls(
            slug=session.slug,
            path=session.path,
            session_type=SessionType.JSON,
            state=session.state.value,
            # ...
        )
```

## Comparison: Screen vs JSON Mode

| Aspect | Screen Mode | JSON Mode |
|--------|-------------|-----------|
| **Output Format** | Terminal text (ANSI) | Structured JSON |
| **State Detection** | Pattern matching | Explicit events |
| **Session Persistence** | Screen keeps process alive | Session ID resume |
| **Interactivity** | True interactive | Pseudo-interactive |
| **Tool Prompts** | Can interact manually | Must use --dangerously-skip-permissions |
| **Best For** | Direct terminal access | API/automation |

## When to Use Each Mode

**Use Screen Mode when:**
- You need true interactive access (attach to session)
- You want to manually approve tool executions
- You're using MCP servers interactively

**Use JSON Mode when:**
- Building API/programmatic access
- Integrating with CI/CD pipelines
- You need structured, parseable output
- You're okay with auto-approving tool executions

## Testing the Integration

```bash
# Create a JSON session
curl -X POST http://localhost:32205/json-sessions \
    -H "Content-Type: application/json" \
    -d '{"slug": "TEST", "path": "/home/user/project"}'

# Invoke Claude
curl -X POST "http://localhost:32205/json-sessions/TEST/invoke?prompt=List%20files"

# Get events
curl http://localhost:32205/json-sessions/TEST/events

# Watch events via WebSocket
wscat -c ws://localhost:32205/ws/stream
# Send: {"type": "subscribe", "sessions": ["TEST"]}
# Then invoke and watch claude_event messages
```

## Next Steps

1. **Test on your system** - Run `test_stream_json.sh` to verify JSON output works
2. **Start small** - Add JSON endpoints alongside existing screen endpoints
3. **Iterate on TUI** - Improve event formatting for better display
4. **Add configuration** - Let users choose default session type
5. **Consider hybrid** - Some features might work better with one mode
