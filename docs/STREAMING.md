# CBOS Streaming Transport Layer

## Overview

CBOS v0.6.0 introduces a streaming transport layer that replaces the polling-based architecture with real-time output capture using `script -f` and WebSocket delivery.

**Key Changes:**
- Sessions launched with `script -f` for real-time I/O capture
- StreamManager watches typescript files for changes
- WebSocket endpoint `/ws/stream` for real-time delivery
- State heuristics disabled (inference deferred)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     GNU Screen Sessions                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ INFRA       │  │ AUTH        │  │ INTEL       │   ...        │
│  │             │  │             │  │             │              │
│  │ script -f   │  │ script -f   │  │ script -f   │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         ▼                ▼                ▼                      │
│    .typescript      .typescript      .typescript                 │
│       files            files            files                    │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     StreamManager                                │
│                                                                  │
│  • Watches ~/claude_streams/*.typescript using watchfiles       │
│  • Tracks byte positions for incremental reads                  │
│  • Emits StreamEvent(session, data, timestamp)                  │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ConnectionManager                            │
│                                                                  │
│  • Manages WebSocket connections                                │
│  • Subscription model: clients subscribe to sessions            │
│  • Broadcasts stream events to subscribed clients               │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     WebSocket Clients                            │
│                                                                  │
│  TUI, Web UI, or custom clients                                 │
│  Connect to ws://127.0.0.1:32205/ws/stream                      │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### StreamManager (`cbos/core/stream.py`)

Watches typescript files and emits events when new content arrives.

```python
from cbos.core.stream import StreamManager, StreamEvent

manager = StreamManager()
manager.on_stream(async_callback)  # Register callback
await manager.start()              # Start watching
```

**Key Methods:**
- `start()` - Start the file watcher
- `stop()` - Stop watching
- `on_stream(callback)` - Register async callback for stream events
- `get_buffer(slug, max_bytes)` - Get current buffer content
- `get_sessions()` - List sessions with typescript files

### ConnectionManager (`cbos/api/websocket.py`)

Manages WebSocket connections and subscriptions.

```python
from cbos.api.websocket import connection_manager

client = await connection_manager.connect(websocket)
await connection_manager.subscribe(websocket, ["INFRA", "AUTH"])
await connection_manager.broadcast_stream(event)
```

### Configuration (`cbos/core/config.py`)

```python
from cbos.core.config import get_config

config = get_config()
config.stream.stream_dir      # ~/claude_streams
config.stream.stream_flush    # True (use -f flag)
config.stream.max_buffer_size # 100000 bytes
```

Environment variables:
- `CBOS_STREAM_STREAM_DIR` - Override stream directory
- `CBOS_STREAM_MAX_BUFFER_SIZE` - Override max buffer size

## WebSocket Protocol

### Endpoint

```
ws://127.0.0.1:32205/ws/stream
```

### Client → Server Messages

**Subscribe to sessions:**
```json
{"type": "subscribe", "sessions": ["INFRA", "AUTH"]}
{"type": "subscribe", "sessions": ["*"]}
```

**Unsubscribe:**
```json
{"type": "unsubscribe", "sessions": ["INFRA"]}
```

**Send input to session:**
```json
{"type": "send", "session": "INFRA", "text": "yes"}
```

**Interrupt session (Ctrl+C):**
```json
{"type": "interrupt", "session": "INFRA"}
```

**Get current buffer:**
```json
{"type": "get_buffer", "session": "INFRA"}
```

**List sessions:**
```json
{"type": "list_sessions"}
```

### Server → Client Messages

**Initial session list:**
```json
{"type": "sessions", "sessions": [...]}
```

**Available streams:**
```json
{"type": "available_streams", "sessions": ["INFRA", "AUTH"]}
```

**Subscription confirmation:**
```json
{"type": "subscribed", "sessions": ["INFRA", "AUTH"]}
```

**Stream data (real-time):**
```json
{
  "type": "stream",
  "session": "INFRA",
  "data": "...terminal output...",
  "ts": 1704326400.123
}
```

**Buffer response:**
```json
{"type": "buffer", "session": "INFRA", "data": "..."}
```

**Operation results:**
```json
{"type": "send_result", "session": "INFRA", "success": true}
{"type": "interrupt_result", "session": "INFRA", "success": true}
```

## Session Launch

New sessions are launched with `script -f` wrapping:

```bash
screen -dmS SLUG bash -c 'script -f --timing=~/claude_streams/SLUG.timing \
  ~/claude_streams/SLUG.typescript \
  -c "cd /path && NO_COLOR=1 claude"'
```

This creates:
- `~/claude_streams/SLUG.typescript` - Raw terminal output
- `~/claude_streams/SLUG.timing` - Timing data for replay

## Legacy Sessions

Existing sessions (launched before v0.6.0) do not have typescript files and will not stream automatically.

**Options:**
1. **Restart sessions** - Kill and relaunch through CBOS API
2. **Hybrid mode** - REST API still works for non-streaming sessions
3. **Manual migration** - Use `reptyr` or restart manually

## State Detection

State heuristics are **disabled** in streaming mode:

```python
# cbos/core/store.py
class SessionStore:
    STREAMING_MODE = True  # Disable state detection
```

All sessions show `idle` state. State inference from stream content is planned for future implementation.

## Files

| File | Purpose |
|------|---------|
| `cbos/core/stream.py` | StreamManager - file watching |
| `cbos/core/config.py` | Stream configuration |
| `cbos/api/websocket.py` | ConnectionManager - WebSocket handling |
| `cbos/api/main.py` | `/ws/stream` endpoint |
| `cbos/core/screen.py` | `launch()` with script -f |
| `cbos/core/store.py` | STREAMING_MODE flag |
| `cbos/tui/app.py` | TUI WebSocket client |

## Example Client

```python
import asyncio
import json
import websockets

async def stream_client():
    async with websockets.connect("ws://127.0.0.1:32205/ws/stream") as ws:
        # Subscribe to all sessions
        await ws.send(json.dumps({
            "type": "subscribe",
            "sessions": ["*"]
        }))

        # Receive stream events
        async for message in ws:
            data = json.loads(message)

            if data["type"] == "stream":
                session = data["session"]
                content = data["data"]
                print(f"[{session}] {content}", end="")

asyncio.run(stream_client())
```

## Troubleshooting

**No stream events received:**
- Check `~/claude_streams/` for typescript files
- Session may need restart with streaming enabled
- Verify subscription: look for `subscribed` response

**WebSocket connection fails:**
- Ensure cbos service is running: `systemctl status cbos`
- Check port 32205 is accessible

**Typescript files not created:**
- Session was launched before v0.6.0
- Check `script` command is available: `which script`

**Check logs:**
```bash
sudo journalctl -u cbos -f | grep stream
```
