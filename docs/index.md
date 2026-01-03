# CBOS Documentation

CBOS (Claude Code Operating System) is a session manager for running multiple Claude Code instances via GNU Screen.

## Quick Start

```bash
# Check API status (already running as systemd service)
sudo systemctl status cbos

# Launch the TUI
cbos

# Or run via Python
python -m cbos.tui.app
```

## API Endpoints

Base URL: `http://127.0.0.1:32900`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sessions` | GET | List all sessions |
| `/sessions/status` | GET | Summary status counts |
| `/sessions/waiting` | GET | Sessions waiting for input |
| `/sessions/{slug}` | GET | Get session details |
| `/sessions` | POST | Create new session |
| `/sessions/{slug}` | DELETE | Kill session |
| `/sessions/{slug}/send` | POST | Send input |
| `/sessions/{slug}/interrupt` | POST | Send Ctrl+C |
| `/sessions/{slug}/buffer` | GET | Get buffer content |
| `/ws` | WebSocket | Real-time updates |

## TUI Keybindings

| Key | Action |
|-----|--------|
| `j/k` | Navigate sessions |
| `Enter` | Focus input field |
| `Escape` | Back to session list |
| `r` | Refresh |
| `Ctrl+C` | Interrupt selected session |
| `a` | Show attach command |
| `q` | Quit |

## Documentation

- [START-HERE.md](START-HERE.md) - Screen management guide
- [MVP-PLAN.md](MVP-PLAN.md) - Architecture and implementation plan
