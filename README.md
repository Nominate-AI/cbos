# CBOS - Claude Code Operating System

A session manager for running multiple Claude Code instances via GNU Screen.

## Features

- Launch and manage multiple Claude Code sessions
- Real-time status monitoring (waiting, thinking, working, idle)
- Send input to sessions via API or TUI
- Stash responses for later
- WebSocket-based real-time updates

## Installation

```bash
pip install -e .
```

## Usage

### Start the API server

```bash
cbos-api
# or
uvicorn cbos.api.main:app --port 8901
```

### Launch the TUI

```bash
cbos
```

### API Endpoints

- `GET /sessions` - List all sessions
- `GET /sessions/{slug}` - Get session details
- `POST /sessions` - Create a new session
- `DELETE /sessions/{slug}` - Kill a session
- `POST /sessions/{slug}/send` - Send input to a session
- `GET /sessions/{slug}/buffer` - Get session buffer
- `WS /ws` - WebSocket for real-time updates

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```
