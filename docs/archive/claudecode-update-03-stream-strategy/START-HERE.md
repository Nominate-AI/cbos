# CBOS Quick Start Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        CBOS Server                               │
│         (Persistent - manages Claude Code sessions)              │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  Session 1  │  │  Session 2  │  │  Session N  │             │
│  │ (Claude CC) │  │ (Claude CC) │  │ (Claude CC) │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
│         │                │                │                     │
│         └────────────────┼────────────────┘                     │
│                          │                                      │
│                 ┌────────┴────────┐                             │
│                 │    Event Bus    │────► AI Listeners (future)  │
│                 └────────┬────────┘                             │
│                          │                                      │
│                 ┌────────┴────────┐                             │
│                 │  WebSocket Hub  │                             │
│                 └────────┬────────┘                             │
└──────────────────────────┼──────────────────────────────────────┘
                           │ ws://localhost:8080
          ┌────────────────┼────────────────┐
          │                │                │
     ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
     │ TUI #1  │      │ TUI #2  │      │  Web?   │
     │  (Ink)  │      │  (Ink)  │      │         │
     └─────────┘      └─────────┘      └─────────┘
```

## File Overview

|File                            |Purpose                                           |
|--------------------------------|--------------------------------------------------|
|`cbos-websocket-architecture.md`|Full architecture documentation                   |
|`cbos-server.ts`                |WebSocket server that manages Claude Code sessions|
|`cbos-client.ts`                |Client SDK with React hooks for Ink               |
|`cbos-tui-websocket.tsx`        |Ink-based TUI that connects to server             |
|`cbos-packages.json`            |Package.json files for monorepo setup             |

## Quick Start

### 1. Set Up Project Structure

```bash
mkdir cbos && cd cbos

# Create monorepo structure
mkdir -p packages/cbos-server/src
mkdir -p packages/cbos-client/src  
mkdir -p packages/cbos-tui/src

# Copy files (from this conversation's outputs)
cp cbos-server.ts packages/cbos-server/src/index.ts
cp cbos-client.ts packages/cbos-client/src/index.ts
cp cbos-tui-websocket.tsx packages/cbos-tui/src/index.tsx

# Extract package.json files from cbos-packages.json
# (The file contains multiple package.json separated by ---FILE: markers)
```

### 2. Install Dependencies

```bash
# Root package.json
cat > package.json << 'EOF'
{
  "name": "cbos",
  "private": true,
  "workspaces": ["packages/*"],
  "scripts": {
    "dev:server": "npm run dev -w @cbos/server",
    "dev:tui": "npm run dev -w @cbos/tui"
  }
}
EOF

npm install
```

### 3. Run the Server

```bash
# Terminal 1: Start server
npm run dev:server

# Output:
# [CBOS Server] Listening on ws://localhost:8080
# [EventBus] Registered listener: event-logger
```

### 4. Run the TUI

```bash
# Terminal 2: Start TUI
npm run dev:tui

# Or with custom server URL:
CBOS_SERVER=ws://localhost:8080 npm run dev:tui
```

### 5. Use It

```
┌─ CBOS ──────────────────────────── View: list | ● connected ─┐
│                                                               │
│  Sessions                                                     │
│  ❯ ● my-session  [3]                                         │
│    ○ test-session  [0]                                       │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│ [L]ist [D]etail [I]nput [O]utput [N]ew [S]top [Q]uit         │
└───────────────────────────────────────────────────────────────┘
```

**Keyboard shortcuts:**

- `L` - Session list
- `D` - Session detail
- `I` - Input prompt (send message to Claude)
- `O` - Output stream view
- `N` - Create new session
- `S` - Stop selected session
- `Q` - Quit

## Key Features

### Sessions Persist Across TUI Restarts

Sessions are managed by the server, not the TUI. You can:

1. Start a session in TUI #1
1. Close TUI #1
1. Open TUI #2
1. Continue the same session

### Multiple TUI Clients

Multiple TUIs can connect simultaneously:

- All see real-time output streams
- Owner can send input
- Collaborators can send input (queued)
- Observers can only watch

### AI Listener Hooks (Stubbed)

The server has an event bus that AI listeners can subscribe to:

```typescript
// In cbos-server.ts
class AutoResponderListener implements AIListener {
  name = 'auto-responder';

  shouldHandle(event: SessionEvent): boolean {
    return event.type === 'claude:waiting';
  }

  async handle(event: SessionEvent, context: ListenerContext): Promise<void> {
    // Future: Analyze context, generate response, inject
    // const response = await aiGenerate(event.data.context);
    // await context.injectInput(event.sessionId, response);
  }
}

// Register it:
eventBus.registerListener(new AutoResponderListener());
```

## Development Workflow

### Adding New Features

1. **New server functionality** → Edit `cbos-server.ts`
1. **New client methods** → Edit `cbos-client.ts`, add hooks
1. **New UI views** → Edit `cbos-tui-websocket.tsx`

### Testing Without Claude

For development, you can mock the Claude process in `cbos-server.ts`:

```typescript
// In ClaudeProcess.start(), replace spawn with mock:
async start(): Promise<void> {
  this.onStatusChange('running');
  
  // Mock: simulate Claude responses
  setTimeout(() => {
    this.onOutput('Hello! How can I help?', 'stdout');
    this.onWaiting('Hello! How can I help?');
  }, 1000);
}
```

## Next Steps

### MVP (Phase 1)

- [x] WebSocket server architecture
- [x] Client SDK with React hooks
- [x] Basic Ink TUI
- [ ] Test with real Claude Code sessions
- [ ] Error handling polish
- [ ] Session persistence (save/restore)

### AI Integration (Phase 2)

- [ ] Implement AIListener interface
- [ ] Add response generation logic
- [ ] Pattern matching for auto-response triggers
- [ ] Queue management for multi-response scenarios

### Advanced Features (Phase 3)

- [ ] Web UI client (React)
- [ ] Session templates/presets
- [ ] Batch operations
- [ ] Metrics/analytics dashboard

## Environment Variables

|Variable     |Default              |Description       |
|-------------|---------------------|------------------|
|`CBOS_PORT`  |`8080`               |Server listen port|
|`CBOS_SERVER`|`ws://localhost:8080`|TUI server URL    |

## Troubleshooting

### “Not connected” in TUI

- Check server is running
- Check `CBOS_SERVER` URL is correct
- Check firewall/network

### Claude process not starting

- Ensure `claude` CLI is installed and in PATH
- Check `claude doctor` passes
- Verify authentication (`claude /login`)

### WebSocket connection drops

- Server has auto-reconnect built in
- Check server logs for errors
- Increase `maxReconnectAttempts` if needed
