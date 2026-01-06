# CBOS - Claude Code Operating System

A session manager for running multiple Claude Code instances with real-time monitoring and orchestration.

```
┌─────────────────────────────────────────────────────────────┐
│ CBOS - Claude Code Session Manager                          │
├─────────────────────────────────────────────────────────────┤
│ Sessions                                                    │
│   ● AUTH      ~/projects/auth-service         [waiting]     │
│   ◑ BACKEND   ~/projects/api-server           [working]     │
│   ◐ FRONTEND  ~/projects/web-app              [thinking]    │
│   ○ DOCS      ~/projects/documentation        [idle]        │
├─────────────────────────────────────────────────────────────┤
│ [j/k]nav [i]nput [n]ew [c]trl-C [q]uit  │ 4 sessions │ ● 1  │
└─────────────────────────────────────────────────────────────┘
```

## Features

- **Multi-Session Management**: Run multiple Claude Code instances simultaneously
- **Real-Time Updates**: WebSocket-based instant state changes (no polling!)
- **Smart Input Detection**: Uses Claude Code's native hook system
- **Vim-Style Navigation**: j/k keys, familiar workflow
- **Session Persistence**: Sessions survive TUI restarts
- **React-Based TUI**: Built with Ink for a modern terminal experience

## Quickstart

```bash
# Clone and install
git clone https://github.com/anthropics/cbos.git
cd cbos/ts
npm install

# Terminal 1: Start the server
npm run dev:server

# Terminal 2: Start the TUI
npm run dev:tui
```

That's it! The server will:
1. Install a Claude Code hook at `~/.claude/hooks/cbos-input-detector.sh`
2. Listen on `ws://localhost:32205`
3. Watch for Claude "waiting for input" events

## How It Works

```
┌──────────────┐     hook fires      ┌──────────────┐
│ Claude Code  │ ─────────────────▶  │ events.jsonl │
│  (session)   │   "end_turn"        │              │
└──────────────┘                     └──────┬───────┘
                                            │ watch
                                            ▼
┌──────────────┐     WebSocket       ┌──────────────┐
│     TUI      │ ◀────────────────── │    Server    │
│    (Ink)     │     broadcast       │  (Node.js)   │
└──────────────┘                     └──────────────┘
```

When Claude finishes a turn and waits for input, a hook fires and writes to `events.jsonl`. The server watches this file and broadcasts the update to all connected TUI clients instantly.

## Usage

### Keybindings

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `Enter` | Select session |
| `i` | Send input to waiting session |
| `n` | Create new session |
| `c` | Interrupt session (Ctrl+C) |
| `x` | Delete session |
| `d` | Detail view |
| `l` | List view |
| `q` | Quit |

### Session States

| Icon | State | Meaning |
|------|-------|---------|
| ● | waiting | Claude is waiting for your input |
| ◐ | thinking | Claude is generating a response |
| ◑ | working | Claude is executing tools |
| ○ | idle | No active process |
| ✗ | error | Something went wrong |

## Configuration

### Environment Variables

```bash
export CBOS_PORT=32205              # Server port
export CBOS_CLAUDE_COMMAND=claude   # Claude executable path
```

### Config File (optional)

Create `~/.cbos/ts-config.json`:

```json
{
  "port": 32205,
  "claudeCommand": "claude",
  "hookEnabled": true
}
```

## Architecture

CBOS uses a client-server architecture:

- **Server** (`@cbos/server`): Manages sessions, spawns Claude processes, watches for events
- **TUI** (`@cbos/tui`): React/Ink terminal interface, connects via WebSocket

Multiple TUI clients can connect to the same server - great for monitoring from different terminals.

See [docs/OS3.md](./docs/OS3.md) for detailed architecture documentation.

## Development

```bash
# Install dependencies
npm install

# Development with hot reload
npm run dev:server   # Start server
npm run dev:tui      # Start TUI

# Build for production
npm run build

# Run production
npm run server
npm run tui
```

## File Locations

| File | Purpose |
|------|---------|
| `~/.cbos/ts-sessions.json` | Session persistence |
| `~/.cbos/ts-config.json` | Configuration (optional) |
| `~/.claude/hooks/cbos-input-detector.sh` | Stop hook script |
| `~/.claude/cbos/events.jsonl` | Event log |

## Requirements

- Node.js 18+
- Claude Code CLI installed and authenticated

## License

MIT
