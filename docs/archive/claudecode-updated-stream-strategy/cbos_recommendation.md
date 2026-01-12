# CBOS: Recommended Approaches for Claude Code Integration

## TL;DR - Three Options

| Approach | Best For | Complexity | Interactivity |
|----------|----------|------------|---------------|
| **Claude Agent SDK (Recommended)** | Full programmatic control | Medium | Pseudo-interactive |
| **Stream-JSON CLI** | Quick integration | Low | Pseudo-interactive |
| **Screen Scraping (Current)** | Direct terminal access | High | True interactive |

---

## Option 1: Official Claude Agent SDK (RECOMMENDED)

The **Claude Agent SDK** (formerly Claude Code SDK) provides the cleanest programmatic interface.

### Installation

```bash
# Python
pip install claude-agent-sdk

# TypeScript
npm install @anthropic-ai/claude-agent-sdk
```

### Example Usage (Python)

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def run_claude_session(project_path: str, prompt: str):
    """Run a Claude Code interaction and yield events"""
    
    options = ClaudeAgentOptions(
        cwd=project_path,
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob"],
        # Session management
        # resume="session-id-here",  # To continue a session
    )
    
    async for message in query(prompt=prompt, options=options):
        # Message types: assistant, tool_use, tool_result, result, etc.
        yield message

async def main():
    async for msg in run_claude_session("/home/user/project", "List files"):
        print(msg)

asyncio.run(main())
```

### Benefits
- ✅ **Official, supported** by Anthropic
- ✅ **Same tools** as Claude Code CLI (Read, Write, Bash, etc.)
- ✅ **Structured messages** - no parsing needed
- ✅ **Session management** built-in
- ✅ **Hooks support** for custom logic
- ✅ **MCP integration** for extending capabilities

### Integration with CBOS

```python
# cbos/core/sdk_manager.py

from claude_agent_sdk import query, ClaudeAgentOptions
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Optional
import asyncio

@dataclass
class SDKSession:
    slug: str
    path: str
    state: str = "idle"  # idle, running, waiting, complete
    session_id: Optional[str] = None
    messages: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

class SDKSessionManager:
    """Manages Claude sessions using the official Agent SDK"""
    
    def __init__(self):
        self._sessions: dict[str, SDKSession] = {}
        self._callbacks: list = []
    
    def create_session(self, slug: str, path: str) -> SDKSession:
        session = SDKSession(slug=slug, path=path)
        self._sessions[slug] = session
        return session
    
    async def invoke(
        self,
        slug: str,
        prompt: str,
        allowed_tools: list[str] = None,
    ) -> AsyncIterator[dict]:
        """Send a prompt and stream responses"""
        session = self._sessions.get(slug)
        if not session:
            raise ValueError(f"Session {slug} not found")
        
        if session.state == "running":
            raise ValueError(f"Session {slug} is already running")
        
        session.state = "running"
        
        options = ClaudeAgentOptions(
            cwd=session.path,
            allowed_tools=allowed_tools or ["Read", "Write", "Edit", "Bash", "Glob"],
        )
        
        # Resume if we have a session ID
        if session.session_id:
            options.resume = session.session_id
        
        try:
            async for message in query(prompt=prompt, options=options):
                # Store message
                msg_dict = self._message_to_dict(message)
                session.messages.append(msg_dict)
                
                # Extract session ID if available
                if hasattr(message, 'session_id'):
                    session.session_id = message.session_id
                
                yield msg_dict
                await self._emit(slug, msg_dict)
            
            session.state = "complete"
            
        except Exception as e:
            session.state = "error"
            yield {"type": "error", "message": str(e)}
        
    def _message_to_dict(self, message) -> dict:
        """Convert SDK message to dict for WebSocket"""
        if hasattr(message, 'result'):
            return {
                "type": "result",
                "content": message.result,
            }
        elif hasattr(message, 'content'):
            return {
                "type": "assistant",
                "content": self._extract_content(message.content),
            }
        elif hasattr(message, 'tool_name'):
            return {
                "type": "tool_use",
                "tool": message.tool_name,
                "input": getattr(message, 'tool_input', {}),
            }
        else:
            return {"type": "unknown", "raw": str(message)}
    
    def _extract_content(self, content) -> str:
        """Extract text content from various formats"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if hasattr(block, 'text'):
                    texts.append(block.text)
                elif isinstance(block, dict) and 'text' in block:
                    texts.append(block['text'])
            return "\n".join(texts)
        return str(content)
    
    async def _emit(self, slug: str, message: dict):
        for callback in self._callbacks:
            try:
                await callback(slug, message)
            except Exception:
                pass
    
    def on_message(self, callback):
        self._callbacks.append(callback)
```

---

## Option 2: Stream-JSON CLI Mode

For lighter integration without the SDK, use the CLI directly with `--output-format stream-json`.

### How It Works

```bash
# Run Claude with JSON output
claude -p "Your prompt" \
    --output-format stream-json \
    --dangerously-skip-permissions \
    --resume SESSION_ID

# Output: Newline-delimited JSON events
{"type":"init","session_id":"abc123",...}
{"type":"assistant","message":{"content":"..."}}
{"type":"tool_use","tool":{"name":"Read",...}}
{"type":"result","subtype":"success",...}
```

### Python Wrapper

```python
import asyncio
import json
import os

async def invoke_claude(path: str, prompt: str, session_id: str = None):
    """Run Claude CLI and stream JSON events"""
    
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
    ]
    
    if session_id:
        cmd.extend(["--resume", session_id])
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=path,
        env={**os.environ, "NO_COLOR": "1"},
    )
    
    async for line in process.stdout:
        line = line.decode().strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"type": "raw", "content": line}
    
    await process.wait()
```

### Comparison with SDK

| Feature | Agent SDK | Stream-JSON CLI |
|---------|-----------|-----------------|
| Installation | `pip install claude-agent-sdk` | Already have `claude` |
| Message types | Typed objects | JSON dicts |
| Custom tools | Hooks, MCP | CLI flags only |
| Complexity | Medium | Low |

---

## Option 3: Keep Screen-Based (Current Approach)

Your current approach can still work for users who need true interactive access.

### When to Use Screen Mode

- Attaching directly to sessions (`screen -r`)
- Manual tool approval (not using `--dangerously-skip-permissions`)
- MCP servers that require interactive input
- Debugging/development

### Improvements to Current Approach

1. **Use PTY instead of `script -f`** for cleaner output
2. **Parse terminal state** more robustly with state machine
3. **Hybrid mode**: Screen for display, SDK for structured data

---

## Recommended Architecture

Combine all three approaches:

```
┌─────────────────────────────────────────────────────────────────┐
│                         CBOS TUI                                │
│  Select session type when creating:                             │
│  - SDK Mode (recommended) - programmatic, structured            │
│  - Screen Mode - interactive, can attach                        │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CBOS API Server                              │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  SessionRouter                                              ││
│  │  - Routes to SDKSessionManager or ScreenManager             ││
│  │  - Unified WebSocket events                                 ││
│  └─────────────────────────────────────────────────────────────┘│
│                          │                                       │
│        ┌─────────────────┴─────────────────┐                     │
│        ▼                                   ▼                     │
│  ┌──────────────┐                   ┌──────────────┐             │
│  │ SDKSession   │                   │ ScreenSession│             │
│  │ Manager      │                   │ Manager      │             │
│  │              │                   │              │             │
│  │ Uses Agent   │                   │ Uses GNU     │             │
│  │ SDK (Python) │                   │ Screen       │             │
│  └──────────────┘                   └──────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Step 1: Test the SDK

```bash
# Install
pip install claude-agent-sdk

# Set API key
export ANTHROPIC_API_KEY=your-key

# Test
python -c "
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    async for msg in query('Say hello', ClaudeAgentOptions()):
        print(msg)

asyncio.run(main())
"
```

### Step 2: Add SDK Manager to CBOS

Copy the `SDKSessionManager` class above into `cbos/core/sdk_manager.py`.

### Step 3: Add API Endpoints

```python
# In cbos/api/main.py

from ..core.sdk_manager import SDKSessionManager

sdk_manager = SDKSessionManager()

@app.post("/sdk-sessions", response_model=dict)
def create_sdk_session(req: SessionCreate):
    session = sdk_manager.create_session(req.slug, req.path)
    return {"slug": session.slug, "path": session.path, "state": session.state}

@app.post("/sdk-sessions/{slug}/invoke")
async def invoke_sdk_session(slug: str, prompt: str):
    async def run():
        async for msg in sdk_manager.invoke(slug, prompt):
            pass  # Events broadcast via WebSocket
    asyncio.create_task(run())
    return {"status": "started"}
```

### Step 4: Update WebSocket

Add callback to broadcast SDK events:

```python
async def on_sdk_message(slug: str, message: dict):
    await connection_manager.broadcast_sdk_event(slug, message)

sdk_manager.on_message(on_sdk_message)
```

---

## Summary

**For your network-based Claude Code environment, I recommend:**

1. **Primary**: Use the **Claude Agent SDK** for new sessions
   - Clean API, structured messages, session management built-in
   
2. **Secondary**: Keep **Screen-based sessions** for:
   - Direct terminal access needs
   - Backwards compatibility
   - Debugging

3. **Optional**: Use **Stream-JSON CLI** as a lightweight alternative if the SDK is overkill

The SDK approach gives you:
- ✅ Structured, typed messages
- ✅ No screen scraping or ANSI parsing
- ✅ Session resume built-in
- ✅ Same tools as Claude Code CLI
- ✅ Official Anthropic support
