# CBOS - Claude Code Operating System

A session manager for running multiple Claude Code instances with real-time streaming, WebSocket API, and terminal UI.

## Features

- **Multi-session management** - Run multiple Claude Code instances in parallel
- **Real-time streaming** - Live terminal output via WebSocket (no polling)
- **Terminal UI** - Navigate sessions with vim-like keybindings
- **WebSocket API** - Send input, receive streams, manage sessions
- **GNU Screen integration** - Reliable session persistence

## Prerequisites

- Python 3.11+
- GNU Screen
- Claude Code CLI (`claude` command available in PATH)

```bash
# Verify prerequisites
python3 --version    # 3.11+
screen --version     # GNU Screen
which claude         # Claude Code CLI
```

## Installation

### 1. Clone and install

```bash
git clone https://github.com/Nominate-AI/cbos.git
cd cbos

# Create/activate virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install -e .
```

### 2. Create required directories

```bash
mkdir -p ~/claude_streams ~/claude_logs
```

### 3. Set up systemd service (recommended)

```bash
# Copy service file
sudo cp systemd/cbos.service /etc/systemd/system/

# Edit paths if needed (default assumes ~/.pyenv/versions/nominates)
sudo vim /etc/systemd/system/cbos.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable cbos
sudo systemctl start cbos

# Verify
systemctl status cbos
```

## Quick Start

### Option A: Run manually

```bash
# Terminal 1: Start API server
cbos-api

# Terminal 2: Launch TUI
cbos
```

### Option B: Use systemd service

```bash
# Start service
sudo systemctl start cbos

# Launch TUI (connects to running service)
cbos
```

## Creating Sessions

Sessions are created through the CBOS API - you don't start screen sessions manually.

```bash
# Create a new session
curl -X POST http://localhost:32205/sessions \
  -H "Content-Type: application/json" \
  -d '{"slug": "MYPROJECT", "path": "/home/user/myproject"}'
```

CBOS automatically:
- Creates a GNU Screen session with the specified name
- Wraps Claude in `script -f` for real-time streaming capture
- Sets `NO_COLOR=1` for cleaner terminal output
- Starts Claude Code in the specified working directory

**What runs under the hood:**
```bash
screen -dmS MYPROJECT -L -Logfile ~/claude_logs/MYPROJECT.log bash -c \
  "script -f --timing=~/claude_streams/MYPROJECT.timing \
   ~/claude_streams/MYPROJECT.typescript \
   -c 'cd /home/user/myproject && NO_COLOR=1 claude'"
```

**Note:** Existing screen sessions started manually (not through CBOS) will appear in the list but won't stream - they weren't wrapped with `script -f`. Kill and recreate them through CBOS to enable streaming.

**To attach directly** (bypass CBOS TUI):
```bash
screen -r MYPROJECT
```

## TUI Usage

```
┌─────────────────────────────────────────────────────────────┐
│  Sessions     │  Buffer Content                             │
│  ─────────    │  ─────────────                              │
│  ● AUTH       │  > What should I do next?                   │
│  ○ INTEL      │                                             │
│  ◐ DOCS       │  ● Thinking about your request...           │
│  ○ APP        │                                             │
├───────────────┴─────────────────────────────────────────────┤
│  ● streaming │ CBOS v0.7.0                                  │
└─────────────────────────────────────────────────────────────┘
```

### Keybindings

| Key | Action |
|-----|--------|
| `j/k` | Navigate sessions |
| `Enter` | Focus input field |
| `Escape` | Back to session list |
| `Ctrl+C` | Send interrupt to session |
| `r` | Reconnect WebSocket |
| `a` | Show attach command |
| `s` | Get AI suggestion |
| `q` | Quit |

### Session States

| Icon | State | Meaning |
|------|-------|---------|
| `●` | waiting | Prompt visible, awaiting input |
| `◐` | thinking | Claude is processing |
| `◑` | working | Executing tools |
| `○` | idle | No activity detected |

## API Reference

### REST Endpoints

```bash
# List sessions
curl http://localhost:32205/sessions

# Create session
curl -X POST http://localhost:32205/sessions \
  -H "Content-Type: application/json" \
  -d '{"slug": "MYPROJECT", "path": "/path/to/project"}'

# Send input
curl -X POST http://localhost:32205/sessions/MYPROJECT/send \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello Claude"}'

# Send interrupt (Ctrl+C)
curl -X POST http://localhost:32205/sessions/MYPROJECT/interrupt

# Get buffer
curl http://localhost:32205/sessions/MYPROJECT/buffer

# Kill session
curl -X DELETE http://localhost:32205/sessions/MYPROJECT
```

### WebSocket Streaming

Connect to `ws://localhost:32205/ws/stream` for real-time updates.

```python
import asyncio
import websockets
import json

async def stream():
    async with websockets.connect("ws://localhost:32205/ws/stream") as ws:
        # Subscribe to all sessions
        await ws.send(json.dumps({
            "type": "subscribe",
            "sessions": ["*"]  # or ["AUTH", "INTEL"]
        }))

        # Receive stream events
        async for message in ws:
            data = json.loads(message)
            if data["type"] == "stream":
                print(f"[{data['session']}] {data['data']}")

asyncio.run(stream())
```

#### WebSocket Messages

**Client → Server:**
```json
{"type": "subscribe", "sessions": ["*"]}
{"type": "send", "session": "AUTH", "text": "yes"}
{"type": "interrupt", "session": "AUTH"}
```

**Server → Client:**
```json
{"type": "sessions", "sessions": [...]}
{"type": "stream", "session": "AUTH", "data": "...", "ts": 1704326400.123}
{"type": "subscribed", "sessions": ["AUTH"]}
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                         TUI (cbos)                           │
│                    WebSocket Client                          │
└─────────────────────────────┬────────────────────────────────┘
                              │ ws://localhost:32205/ws/stream
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    CBOS API Server                           │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ REST API    │  │ WebSocket    │  │ StreamManager    │    │
│  │ /sessions   │  │ /ws/stream   │  │ (watchfiles)     │    │
│  └─────────────┘  └──────────────┘  └────────┬─────────┘    │
└──────────────────────────────────────────────┼───────────────┘
                                               │ watches
                                               ▼
┌──────────────────────────────────────────────────────────────┐
│                   ~/claude_streams/                          │
│  AUTH.typescript  INTEL.typescript  DOCS.typescript  ...    │
└──────────────────────────────────────────────────────────────┘
                              ▲ script -f writes
                              │
┌──────────────────────────────────────────────────────────────┐
│                      GNU Screen Sessions                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│  │  AUTH    │  │  INTEL   │  │  DOCS    │  ...              │
│  │ (claude) │  │ (claude) │  │ (claude) │                   │
│  └──────────┘  └──────────┘  └──────────┘                   │
└──────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CBOS_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `CBOS_STREAM_DIR` | `~/claude_streams` | Directory for typescript files |

### systemd Service

The service file at `/etc/systemd/system/cbos.service`:

```ini
[Unit]
Description=CBOS - Claude Code Session Manager API
After=network.target

[Service]
Type=simple
User=yourusername
Group=yourusername
WorkingDirectory=/path/to/cbos
Environment="PATH=/home/user/.local/bin:/usr/local/bin:/usr/bin"
Environment="CBOS_LOG_LEVEL=INFO"
ExecStart=/path/to/venv/bin/uvicorn cbos.api.main:app --host 127.0.0.1 --port 32205
Restart=always
RestartSec=5
SyslogIdentifier=cbos
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run API server in development
uvicorn cbos.api.main:app --reload --port 32205

# View logs
sudo journalctl -u cbos -f
```

## Troubleshooting

### Session not streaming

Check if the session was created with streaming enabled:
```bash
# Session should show script wrapper in process tree
pstree -a $(pgrep -f "SCREEN.*MYSESSION")
```

Older sessions (created before streaming) need to be restarted.

### WebSocket not connecting

```bash
# Check if API is running
curl http://localhost:32205/sessions

# Check service status
systemctl status cbos
```

### Claude not receiving input

Input requires carriage return. If using the API directly:
```bash
# Use the /send endpoint (handles CR automatically)
curl -X POST http://localhost:32205/sessions/AUTH/send \
  -H "Content-Type: application/json" \
  -d '{"text": "your input here"}'
```

## License

MIT
