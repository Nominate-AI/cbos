# CBOS Quick Start

## What is CBOS?

CBOS (Claude Code Operating System) is a session manager for running multiple Claude Code instances via GNU Screen. It provides:

- Real-time status monitoring of all Claude sessions
- Send input to sessions waiting for responses
- Terminal UI for managing concurrent sessions
- REST API + WebSocket for programmatic access

## Installation

```bash
source ~/.pyenv/versions/nominates/bin/activate
cd ~/projects/nominate/cbos
pip install -e ".[dev]"
```

## Running

### Start the API (systemd)

```bash
sudo systemctl start cbos
sudo systemctl status cbos
```

### Launch the TUI

```bash
cbos
```

Or in a screen session:
```bash
screen -S CBOS_TUI cbos
```

## TUI Keybindings

| Key | Action |
|-----|--------|
| `j/k` | Navigate session list |
| `Enter` | Focus input field |
| `Escape` | Return to session list |
| `r` | Refresh sessions |
| `a` | Show attach command |
| `Ctrl+C` | Send interrupt to session |
| `q` | Quit |

## Session States

| Icon | State | Meaning |
|------|-------|---------|
| `●` | waiting | Claude waiting for user input |
| `◐` | thinking | Claude processing |
| `◑` | working | Claude executing tools |
| `○` | idle | No recent activity |
| `✗` | error | Session in error state |

## API Endpoints

Base URL: `http://127.0.0.1:32205` (local) or `https://os.nominate.ai` (external, PIN protected)

```bash
# List all sessions
curl http://127.0.0.1:32205/sessions

# Get session details
curl http://127.0.0.1:32205/sessions/AUTH

# Send input to a session
curl -X POST http://127.0.0.1:32205/sessions/AUTH/send \
  -H "Content-Type: application/json" \
  -d '{"text": "yes"}'

# Get session buffer
curl http://127.0.0.1:32205/sessions/AUTH/buffer?lines=50
```

## Service Management

```bash
# View logs
sudo journalctl -u cbos -f

# Restart service
sudo systemctl restart cbos

# Stop service
sudo systemctl stop cbos
```

## Attaching to Sessions

To attach directly to a Claude Code session:

```bash
screen -r SESSION_NAME
# e.g., screen -r AUTH
```

Detach with `Ctrl+A, D`.
