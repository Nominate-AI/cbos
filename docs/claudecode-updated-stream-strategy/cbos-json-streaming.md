# CBOS JSON Streaming Architecture

## Problem Statement

The current CBOS architecture uses `script -f` to capture terminal output from interactive Claude Code sessions running in GNU Screen. This approach has fundamental issues:

1. **Terminal redraws** - Screen updates multiple lines simultaneously
2. **ANSI escape codes** - Complex to strip reliably  
3. **State detection** - Relies on fragile pattern matching
4. **Synchronization** - Hard to know when output is "complete"

## Solution: Pseudo-Interactive JSON Mode

Instead of running Claude interactively and scraping output, run **repeated non-interactive invocations** that resume the same session.

### Key Claude Code CLI Flags

```bash
-p, --print           # Non-interactive mode (single prompt, single response)
--output-format       # text | json | stream-json
--resume SESSION_ID   # Resume a previous conversation
--continue            # Continue last conversation
--dangerously-skip-permissions  # No permission prompts (for automation)
```

### JSON Event Types

When using `--output-format stream-json`, Claude outputs newline-delimited JSON:

```json
{"type":"init","session_id":"abc123","cwd":"/project"}
{"type":"user","message":"Your prompt here"}
{"type":"assistant","message":{"content":"I'll help you..."}}
{"type":"tool_use","tool":{"name":"Read","input":{"path":"/file.py"}}}
{"type":"tool_result","result":"file contents..."}
{"type":"result","subtype":"success","cost_usd":0.01,"duration_ms":5000}
```

## New Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CBOS TUI                                │
│  WebSocket client, displays parsed JSON events                  │
└─────────────────────────────┬───────────────────────────────────┘
                              │ ws://localhost:32205/ws/stream
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CBOS API Server                              │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              JSONSessionManager                             ││
│  │  - Manages session state (waiting, running, complete)       ││
│  │  - Spawns Claude CLI processes                              ││
│  │  - Parses stream-json output                                ││
│  │  - Broadcasts events to WebSocket clients                   ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────┬───────────────────────────────────┘
                              │ subprocess
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Claude CLI Processes                          │
│  claude -p "prompt" --output-format stream-json --resume ID    │
│                                                                 │
│  Each invocation is short-lived, session persists via resume   │
└─────────────────────────────────────────────────────────────────┘
```

## Session States

| State | Description |
|-------|-------------|
| `idle` | Waiting for user to send a prompt |
| `running` | Claude process is executing |
| `waiting_permission` | Tool needs approval (if not using --dangerously-skip-permissions) |
| `complete` | Response finished, ready for next prompt |
| `error` | Process exited with error |

## API Changes

### New Endpoints

```
POST /sessions/{slug}/invoke
  Body: {"prompt": "Your message", "options": {...}}
  Returns: Starts async invocation, events streamed via WebSocket

GET /sessions/{slug}/events
  Returns: Recent parsed JSON events for this session
```

### WebSocket Protocol Updates

```json
// Server -> Client: Parsed Claude events
{
  "type": "claude_event",
  "session": "AUTH",
  "event": {
    "type": "assistant",
    "message": {"content": "I'll read that file..."}
  },
  "timestamp": 1704326400.123
}

// Server -> Client: Session state change
{
  "type": "session_state",
  "session": "AUTH", 
  "state": "running"
}

// Client -> Server: Send prompt
{
  "type": "invoke",
  "session": "AUTH",
  "prompt": "Yes, please continue"
}
```

## Implementation

### JSONSessionManager

```python
import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional, Callable

class SessionState(Enum):
    IDLE = "idle"
    RUNNING = "running"  
    COMPLETE = "complete"
    ERROR = "error"

@dataclass
class JSONSession:
    slug: str
    path: str
    session_id: Optional[str] = None  # Claude's internal session ID
    state: SessionState = SessionState.IDLE
    events: list[dict] = field(default_factory=list)
    process: Optional[asyncio.subprocess.Process] = None

class JSONSessionManager:
    """Manages Claude Code sessions using JSON streaming mode"""
    
    def __init__(self, claude_command: str = "claude"):
        self.claude_command = claude_command
        self._sessions: dict[str, JSONSession] = {}
        self._callbacks: list[Callable] = []
    
    def create_session(self, slug: str, path: str) -> JSONSession:
        """Create a new session (just metadata, no process yet)"""
        session = JSONSession(slug=slug, path=path)
        self._sessions[slug] = session
        return session
    
    async def invoke(
        self, 
        slug: str, 
        prompt: str,
        skip_permissions: bool = True
    ) -> AsyncIterator[dict]:
        """
        Invoke Claude with a prompt and stream JSON events.
        
        This spawns a Claude process, parses its stream-json output,
        and yields events as they arrive.
        """
        session = self._sessions.get(slug)
        if not session:
            raise ValueError(f"Session {slug} not found")
        
        if session.state == SessionState.RUNNING:
            raise ValueError(f"Session {slug} is already running")
        
        # Build command
        cmd = [
            self.claude_command,
            "-p", prompt,
            "--output-format", "stream-json",
        ]
        
        if skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        
        # Resume existing session or start new
        if session.session_id:
            cmd.extend(["--resume", session.session_id])
        
        session.state = SessionState.RUNNING
        await self._emit_state_change(session)
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=session.path,
                env={**os.environ, "NO_COLOR": "1"}
            )
            session.process = process
            
            # Stream stdout line by line
            async for line in process.stdout:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                    
                try:
                    event = json.loads(line)
                    session.events.append(event)
                    
                    # Extract session_id from init event
                    if event.get("type") == "init":
                        session.session_id = event.get("session_id")
                    
                    yield event
                    await self._emit_event(session, event)
                    
                except json.JSONDecodeError:
                    # Non-JSON output (shouldn't happen but handle gracefully)
                    yield {"type": "raw", "content": line}
            
            # Wait for process to complete
            await process.wait()
            
            if process.returncode == 0:
                session.state = SessionState.COMPLETE
            else:
                stderr = await process.stderr.read()
                session.state = SessionState.ERROR
                yield {"type": "error", "message": stderr.decode('utf-8')}
                
        except Exception as e:
            session.state = SessionState.ERROR
            yield {"type": "error", "message": str(e)}
            
        finally:
            session.process = None
            await self._emit_state_change(session)
    
    async def _emit_event(self, session: JSONSession, event: dict):
        """Notify callbacks of a new event"""
        for callback in self._callbacks:
            try:
                await callback({
                    "type": "claude_event",
                    "session": session.slug,
                    "event": event
                })
            except Exception:
                pass
    
    async def _emit_state_change(self, session: JSONSession):
        """Notify callbacks of state change"""
        for callback in self._callbacks:
            try:
                await callback({
                    "type": "session_state", 
                    "session": session.slug,
                    "state": session.state.value
                })
            except Exception:
                pass
    
    def on_event(self, callback: Callable):
        """Register callback for events"""
        self._callbacks.append(callback)
```

## Migration Path

1. **Keep existing screen-based sessions** - Don't break what works
2. **Add new JSON-based session type** - `SessionType.SCREEN` vs `SessionType.JSON`
3. **Feature flag** - Let users choose which mode per session
4. **Gradual rollout** - Default to JSON for new sessions

## Pros and Cons

### Pros
- ✅ Structured, parseable output
- ✅ Clear event types (assistant, tool_use, result)
- ✅ No ANSI code stripping needed
- ✅ Explicit state transitions
- ✅ Session ID tracking built-in
- ✅ Works well with WebSocket broadcasting

### Cons
- ❌ Each interaction spawns a new process
- ❌ Slight latency between interactions  
- ❌ May not work with all Claude Code features (MCP, etc.)
- ❌ `--dangerously-skip-permissions` bypasses safety prompts

## Alternative: Hybrid Mode

Keep screen-based sessions for the interactive TUI experience, but add JSON mode for:
- Programmatic API access
- Automated workflows
- CI/CD integration

## Next Steps

1. Test `claude -p --output-format stream-json` on your system
2. Verify `--resume` works to continue sessions
3. Implement `JSONSessionManager` in CBOS
4. Add new WebSocket event types
5. Update TUI to handle JSON events
