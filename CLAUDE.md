# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CBOS (Claude Code Operating System) is a session manager for running multiple Claude Code instances via GNU Screen. It provides real-time status monitoring, input management, and a terminal UI for managing concurrent Claude Code sessions.

## Commands

```bash
# Activate environment first
source ~/.pyenv/versions/nominates/bin/activate

# Run the TUI
cbos

# Start the API server (port 32900)
cbos-api
# or: uvicorn cbos.api.main:app --host 127.0.0.1 --port 32900

# Run tests
pytest tests/ -v

# Install in development mode
pip install -e ".[dev]"
```

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                  TUI (cbos/tui/app.py)                     │
│            Textual-based terminal interface                │
└─────────────────────────┬──────────────────────────────────┘
                          │ REST + WebSocket (port 32900)
                          ▼
┌────────────────────────────────────────────────────────────┐
│               FastAPI Server (cbos/api/main.py)            │
│  - /sessions endpoints for CRUD                            │
│  - /ws WebSocket for real-time updates                     │
│  - Background refresh loop (2s polling)                    │
└─────────────────────────┬──────────────────────────────────┘
                          ▼
┌────────────────────────────────────────────────────────────┐
│              SessionStore (cbos/core/store.py)             │
│  - In-memory sessions with JSON persistence                │
│  - Syncs with actual screen sessions                       │
│  - Manages stashed responses                               │
└─────────────────────────┬──────────────────────────────────┘
                          ▼
┌────────────────────────────────────────────────────────────┐
│             ScreenManager (cbos/core/screen.py)            │
│  - list_sessions() from `screen -ls`                       │
│  - launch()/kill() sessions                                │
│  - capture_buffer() via hardcopy                           │
│  - detect_state() from buffer patterns                     │
└─────────────────────────┬──────────────────────────────────┘
                          ▼
┌────────────────────────────────────────────────────────────┐
│                   GNU Screen Sessions                      │
│          AUTH | INTEL | DOCS | APP | ...                   │
└────────────────────────────────────────────────────────────┘
```

## Session State Detection

State is determined by parsing the screen buffer for these patterns:

| State | Pattern |
|-------|---------|
| WAITING | Last line is `>` or `> ` (empty prompt) |
| THINKING | Buffer contains spinner characters `●◐◑◒◓` |
| WORKING | Lines contain tool calls like `Bash(`, `Read(`, `Edit(` |
| ERROR | Contains `Error:` or `Exception:` |
| IDLE | Default when no other patterns match |

## Key Files

- `cbos/core/models.py` - Pydantic models: Session, SessionState, StashedResponse
- `cbos/core/screen.py` - ScreenManager class for GNU Screen interaction
- `cbos/core/store.py` - SessionStore with JSON persistence at `~/.cbos/sessions.json`
- `cbos/api/main.py` - FastAPI app with REST + WebSocket endpoints
- `cbos/tui/app.py` - Textual TUI with vim-like keybindings (j/k navigation)

## API Endpoints

- `GET /sessions` - List all sessions with current state
- `GET /sessions/{slug}` - Get session details
- `POST /sessions` - Create session (body: `{slug, path}`)
- `DELETE /sessions/{slug}` - Kill session
- `POST /sessions/{slug}/send` - Send input (body: `{text}`)
- `POST /sessions/{slug}/interrupt` - Send Ctrl+C
- `GET /sessions/{slug}/buffer` - Get buffer content
- `WS /ws` - Real-time updates
