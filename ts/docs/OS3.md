# OS3: CBOS TypeScript Architecture

> The third iteration of Claude Code Operating System - rebuilt from the ground up in TypeScript with an event-driven architecture.

## Overview

OS3 represents a fundamental shift from the original Python/Screen-based approach to a modern TypeScript stack:

| Aspect | OS1/OS2 (Python) | OS3 (TypeScript) |
|--------|------------------|------------------|
| **Server** | FastAPI + polling | Node.js + WebSocket |
| **TUI** | Textual | Ink (React for terminals) |
| **Input Detection** | Buffer parsing | Claude Code Stop hook |
| **Session Management** | GNU Screen | Direct process spawning |
| **State Updates** | 2s polling loop | Real-time event stream |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CBOS Server (Node.js)                       │
│                    ws://localhost:32205                         │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │SessionStore │  │SessionMgr   │  │  EventWatcher           │ │
│  │ (JSON file) │  │(spawn claude│  │  (chokidar on           │ │
│  │             │  │ processes)  │  │   events.jsonl)         │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│         │                │                    │                 │
│         └────────────────┴────────────────────┘                 │
│                          │                                      │
│                   WebSocket Hub                                 │
│                          │                                      │
└──────────────────────────┼──────────────────────────────────────┘
                           │
              ws://localhost:32205
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐      ┌─────▼─────┐     ┌─────▼─────┐
    │  TUI #1 │      │  TUI #2   │     │  Future   │
    │  (Ink)  │      │  (Ink)    │     │  Web UI   │
    └─────────┘      └───────────┘     └───────────┘
```

## The Stop Hook Strategy

The key innovation in OS3 is using Claude Code's built-in hook system instead of parsing screen buffers.

### How It Works

1. **Hook Installation**: On server start, CBOS installs a Stop hook at `~/.claude/hooks/cbos-input-detector.sh`

2. **Hook Trigger**: When Claude finishes a turn (`stop_reason: "end_turn"`), the hook fires

3. **Event Generation**: The hook extracts context and appends to `~/.claude/cbos/events.jsonl`:
   ```json
   {
     "event": "waiting_for_input",
     "id": "uuid",
     "timestamp": "2025-01-06T12:00:00-08:00",
     "session": {
       "id": "session-abc123",
       "transcript_path": "/path/to/transcript.jsonl"
     },
     "context": {
       "preceding_text": "I've completed the task...",
       "text_preview": "I've completed..."
     }
   }
   ```

4. **Event Watching**: Server watches `events.jsonl` with chokidar, updates session state, broadcasts to TUI clients

### Benefits Over Buffer Parsing

- **Authoritative**: Hook fires exactly when Claude is waiting - no pattern matching
- **Context-Rich**: Access to full transcript, not just visible buffer
- **Reliable**: No false positives from spinner patterns or tool output
- **Low Latency**: Immediate notification vs 2-second polling

## Package Structure

```
cbos/ts/
├── packages/
│   ├── cbos-server/           # Central WebSocket server
│   │   └── src/
│   │       ├── index.ts       # Entry point
│   │       ├── server.ts      # WebSocket server
│   │       ├── models.ts      # TypeScript types
│   │       ├── store.ts       # Session persistence
│   │       ├── session-manager.ts  # Claude process lifecycle
│   │       ├── event-watcher.ts    # Watch events.jsonl
│   │       ├── hook-installer.ts   # Install Stop hook
│   │       └── config.ts      # Configuration
│   │
│   └── cbos-tui/              # Ink-based terminal UI
│       └── src/
│           ├── index.tsx      # Entry point
│           ├── App.tsx        # Root component
│           ├── components/    # React components
│           │   ├── SessionList.tsx
│           │   ├── SessionDetail.tsx
│           │   ├── InputPrompt.tsx
│           │   ├── CreateModal.tsx
│           │   └── StatusBar.tsx
│           └── hooks/
│               └── useServer.ts  # WebSocket client hook
│
├── package.json               # npm workspaces
└── tsconfig.base.json         # Shared TypeScript config
```

## Data Flow

### Creating a Session

```
TUI                     Server                  Store
 │                        │                       │
 │──create_session───────▶│                       │
 │   {slug, path}         │──create()────────────▶│
 │                        │                       │──write JSON
 │                        │◀──session─────────────│
 │◀──session_created──────│                       │
 │                        │──broadcast to others──│
```

### Sending Input (Invoking Claude)

```
TUI                     Server              SessionManager         Claude
 │                        │                       │                  │
 │──send_input───────────▶│                       │                  │
 │   {slug, text}         │──invoke()────────────▶│                  │
 │                        │                       │──spawn───────────▶
 │                        │                       │   claude -p ...   │
 │◀──session_update───────│◀──state: working─────│                  │
 │   state: working       │                       │                  │
 │                        │                       │◀──stdout events──│
 │◀──claude_event─────────│◀──claude_event───────│                  │
```

### Detecting "Waiting for Input"

```
Claude                Hook Script           events.jsonl        Server              TUI
  │                        │                     │                 │                 │
  │──stop(end_turn)───────▶│                     │                 │                 │
  │                        │──append event──────▶│                 │                 │
  │                        │                     │──file change───▶│                 │
  │                        │                     │                 │──parse event    │
  │                        │                     │                 │──update store   │
  │                        │                     │                 │──broadcast─────▶│
  │                        │                     │                 │  session_waiting│
```

## Session States

| State | Icon | Meaning |
|-------|------|---------|
| `idle` | ○ | No active process |
| `thinking` | ◐ | Claude generating response |
| `working` | ◑ | Claude executing tools |
| `waiting` | ● | Claude waiting for input |
| `error` | ✗ | Process error or crash |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CBOS_PORT` | 32205 | WebSocket server port |
| `CBOS_CLAUDE_COMMAND` | `claude` | Path to Claude executable |
| `CBOS_EVENTS_DIR` | `~/.claude/cbos` | Directory for events.jsonl |

### Config File

Optional `~/.cbos/ts-config.json`:
```json
{
  "port": 32205,
  "claudeCommand": "claude",
  "hookEnabled": true
}
```

## TUI Keybindings

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `Enter` | Select / View detail |
| `l` | List view |
| `d` | Detail view |
| `i` | Input mode (send response) |
| `n` | New session |
| `c` | Interrupt (Ctrl+C) |
| `x` | Delete session |
| `q` | Quit |

## WebSocket Protocol

### Client → Server Messages

```typescript
// Subscribe to session updates
{ type: 'subscribe', sessions: ['*'] }  // all
{ type: 'subscribe', sessions: ['AUTH', 'DOCS'] }  // specific

// Session management
{ type: 'create_session', slug: 'AUTH', path: '/path/to/project' }
{ type: 'delete_session', slug: 'AUTH' }
{ type: 'list_sessions' }

// Claude interaction
{ type: 'send_input', slug: 'AUTH', text: 'Yes, proceed' }
{ type: 'interrupt', slug: 'AUTH' }
```

### Server → Client Messages

```typescript
// Session list
{ type: 'sessions', sessions: [...] }

// Session updates
{ type: 'session_created', session: {...} }
{ type: 'session_deleted', slug: 'AUTH' }
{ type: 'session_update', session: {...} }
{ type: 'session_waiting', slug: 'AUTH', context: '...' }

// Claude events (streamed)
{ type: 'claude_event', slug: 'AUTH', event: {...} }

// Errors
{ type: 'error', message: 'Session not found' }
```

## Future Enhancements

### Planned
- [ ] Project discovery (find CLAUDE.md files)
- [ ] Stashed responses
- [ ] AI response suggestions
- [ ] Multi-pane dashboard view

### Potential
- [ ] Web UI client
- [ ] Session templates
- [ ] Automated workflows (AI listeners)
- [ ] Session sharing / collaboration

## Development

```bash
# Install dependencies
cd cbos/ts && npm install

# Development mode (with hot reload)
npm run dev:server  # Terminal 1
npm run dev:tui     # Terminal 2

# Production build
npm run build
npm run server      # Start server
npm run tui         # Start TUI
```

## Migration from Python

OS3 is a clean break - it uses separate persistence (`~/.cbos/ts-sessions.json`) and doesn't share state with the Python version. You can run both side-by-side during transition.

To fully migrate:
1. Start using OS3 for new sessions
2. Let existing Python sessions complete
3. Eventually retire the Python version

---

*OS3 - Because managing Claude shouldn't require parsing terminal buffers.*
