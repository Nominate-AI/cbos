# Claude Code Input Detection Strategy

## Problem Statement

When orchestrating multiple Claude Code instances programmatically (as in CBOS), you need to know when an instance has finished its work and is waiting for user input. This is essential for:

- Session synchronization across multiple instances
- Automated response injection
- Monitoring dashboards
- Queue-based task management

## Recommended Strategy: Hook + Transcript Hybrid

**Use the `Stop` hook for authoritative “waiting” detection, then read the transcript for context.**

### Why This Approach?

|Approach             |Pros                                         |Cons                                               |
|---------------------|---------------------------------------------|---------------------------------------------------|
|JSONL tailing only   |Full conversation stream                     |Must infer state; buffering issues; race conditions|
|Hooks only           |Explicit events; structured data             |Limited context in hook payload                    |
|**Hook + Transcript**|Best of both: explicit trigger + full context|Slightly more complex                              |

The `Stop` hook fires with `stop_reason: "end_turn"` precisely when Claude finishes and awaits input. This is the canonical signal—no inference required. The hook also receives `transcript_path`, letting you pull whatever context you need.

-----

## Implementation

### Directory Structure

```
~/.claude/
├── settings.json          # Hook configuration
├── hooks/
│   └── input-detector.sh  # Main hook script
└── cbos/
    ├── events.jsonl       # Event log (append-only)
    └── current-state.json # Latest state per session (overwritten)
```

### Step 1: The Hook Script

Save as `~/.claude/hooks/input-detector.sh`:

```bash
#!/usr/bin/env bash
#
# Claude Code Input Detector Hook
# Fires when Claude stops and emits structured events for orchestration
#
set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

CBOS_DIR="${CBOS_DIR:-$HOME/.claude/cbos}"
EVENT_LOG="$CBOS_DIR/events.jsonl"
STATE_FILE="$CBOS_DIR/current-state.json"
CONTEXT_LINES=20  # How many transcript lines to include

# Optional integrations
WEBHOOK_URL="${CBOS_WEBHOOK:-}"           # POST events here if set
NAMED_PIPE="${CBOS_PIPE:-}"               # Write to named pipe if set
NOTIFY_DESKTOP="${CBOS_NOTIFY:-false}"    # Desktop notifications

# ============================================================================
# Setup
# ============================================================================

mkdir -p "$CBOS_DIR"

# Read hook payload from stdin
HOOK_INPUT=$(cat)

# Extract fields
STOP_REASON=$(echo "$HOOK_INPUT" | jq -r '.stop_reason // "unknown"')
TRANSCRIPT_PATH=$(echo "$HOOK_INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(basename "${TRANSCRIPT_PATH%.jsonl}" 2>/dev/null || echo "unknown")

# ============================================================================
# Only process "end_turn" — this means waiting for user input
# ============================================================================

if [[ "$STOP_REASON" != "end_turn" ]]; then
    # Claude stopped for other reasons (tool_use, max_tokens, etc.)
    # These don't indicate "waiting for input"
    exit 0
fi

# ============================================================================
# Extract context from transcript
# ============================================================================

PRECEDING_TEXT=""
LAST_TOOL=""
MESSAGE_COUNT=0

if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
    # Get the last assistant message content
    PRECEDING_TEXT=$(tac "$TRANSCRIPT_PATH" 2>/dev/null | \
        grep -m1 '"role":"assistant"' | \
        jq -r '
            .message.content | 
            if type == "array" then 
                map(select(.type == "text").text) | join("\n")
            else 
                . // ""
            end
        ' 2>/dev/null || echo "")
    
    # Get last tool used (if any)
    LAST_TOOL=$(tac "$TRANSCRIPT_PATH" 2>/dev/null | \
        grep -m1 '"type":"tool_use"' | \
        jq -r '.name // empty' 2>/dev/null || echo "")
    
    # Count messages in session
    MESSAGE_COUNT=$(wc -l < "$TRANSCRIPT_PATH" 2>/dev/null || echo 0)
fi

# ============================================================================
# Build event payload
# ============================================================================

TIMESTAMP=$(date -Iseconds)
EVENT_ID=$(uuidgen 2>/dev/null || echo "$$-$RANDOM")

EVENT=$(jq -nc \
    --arg id "$EVENT_ID" \
    --arg ts "$TIMESTAMP" \
    --arg session "$SESSION_ID" \
    --arg transcript "$TRANSCRIPT_PATH" \
    --arg preceding "$PRECEDING_TEXT" \
    --arg last_tool "$LAST_TOOL" \
    --argjson msg_count "$MESSAGE_COUNT" \
    '{
        event: "waiting_for_input",
        id: $id,
        timestamp: $ts,
        session: {
            id: $session,
            transcript_path: $transcript,
            message_count: $msg_count
        },
        context: {
            preceding_text: $preceding,
            last_tool: (if $last_tool == "" then null else $last_tool end),
            text_preview: ($preceding | if length > 200 then .[:200] + "..." else . end)
        }
    }')

# ============================================================================
# Output to all configured destinations
# ============================================================================

# 1. Append to event log (primary)
echo "$EVENT" >> "$EVENT_LOG"

# 2. Update current state file (for polling-based consumers)
jq -nc \
    --arg session "$SESSION_ID" \
    --arg ts "$TIMESTAMP" \
    --arg status "waiting" \
    '{($session): {status: $status, since: $ts}}' \
    | jq -s 'add' "$STATE_FILE" 2>/dev/null - > "$STATE_FILE.tmp" \
    && mv "$STATE_FILE.tmp" "$STATE_FILE" \
    || echo "$EVENT" | jq '{(.session.id): {status:"waiting", since:.timestamp}}' > "$STATE_FILE"

# 3. Named pipe (for real-time streaming to other processes)
if [[ -n "$NAMED_PIPE" && -p "$NAMED_PIPE" ]]; then
    echo "$EVENT" > "$NAMED_PIPE" &
fi

# 4. Webhook (for remote integrations)
if [[ -n "$WEBHOOK_URL" ]]; then
    curl -s -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "$EVENT" &>/dev/null &
fi

# 5. Desktop notification
if [[ "$NOTIFY_DESKTOP" == "true" ]]; then
    PREVIEW=$(echo "$EVENT" | jq -r '.context.text_preview')
    if command -v osascript &>/dev/null; then
        osascript -e "display notification \"$PREVIEW\" with title \"Claude Ready: $SESSION_ID\""
    elif command -v notify-send &>/dev/null; then
        notify-send "Claude Ready: $SESSION_ID" "$PREVIEW"
    fi
fi

# 6. Debug output (stderr, visible if running hook manually)
echo "[$(date +%H:%M:%S)] SESSION $SESSION_ID WAITING FOR INPUT" >&2

exit 0
```

Make executable:

```bash
chmod +x ~/.claude/hooks/input-detector.sh
```

### Step 2: Configure the Hook

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "command": ["bash", "~/.claude/hooks/input-detector.sh"]
      }
    ]
  }
}
```

Or configure interactively in Claude Code TUI:

```
/hooks
→ Add hook
→ Event: Stop
→ Matcher: *
→ Command: bash ~/.claude/hooks/input-detector.sh
```

### Step 3: Consume Events

#### Option A: Tail the Event Log

```bash
# Simple monitoring
tail -F ~/.claude/cbos/events.jsonl | jq .

# Filter for specific session
tail -F ~/.claude/cbos/events.jsonl | jq 'select(.session.id | contains("abc123"))'

# Just get notifications
tail -F ~/.claude/cbos/events.jsonl | jq -r '"[\(.timestamp)] \(.session.id): \(.context.text_preview)"'
```

#### Option B: Named Pipe for Real-Time Streaming

```bash
# Setup (once)
mkfifo ~/.claude/cbos/events.pipe
export CBOS_PIPE=~/.claude/cbos/events.pipe

# Consumer (run in separate terminal/process)
while true; do
    cat ~/.claude/cbos/events.pipe | jq -c .
done

# Or with a processing script
cat ~/.claude/cbos/events.pipe | while read -r event; do
    session=$(echo "$event" | jq -r '.session.id')
    echo "Session $session is ready for input"
    # Trigger your orchestration logic here
done
```

#### Option C: Poll State File

```bash
# Check if any session is waiting
jq -r 'to_entries[] | select(.value.status == "waiting") | .key' ~/.claude/cbos/current-state.json

# In a loop
while true; do
    waiting=$(jq -r 'to_entries[] | select(.value.status == "waiting") | .key' ~/.claude/cbos/current-state.json 2>/dev/null)
    if [[ -n "$waiting" ]]; then
        echo "Sessions waiting: $waiting"
    fi
    sleep 1
done
```

#### Option D: TypeScript/Node.js Consumer

```typescript
import { watch } from 'fs';
import { createReadStream } from 'fs';
import { createInterface } from 'readline';

const EVENT_LOG = `${process.env.HOME}/.claude/cbos/events.jsonl`;

interface WaitingEvent {
  event: 'waiting_for_input';
  id: string;
  timestamp: string;
  session: {
    id: string;
    transcript_path: string;
    message_count: number;
  };
  context: {
    preceding_text: string;
    last_tool: string | null;
    text_preview: string;
  };
}

// Track file position for incremental reads
let lastPosition = 0;

async function processNewEvents() {
  const rl = createInterface({
    input: createReadStream(EVENT_LOG, { start: lastPosition }),
    crlfDelay: Infinity,
  });

  for await (const line of rl) {
    if (!line.trim()) continue;
    
    try {
      const event: WaitingEvent = JSON.parse(line);
      lastPosition += Buffer.byteLength(line) + 1; // +1 for newline
      
      console.log(`[${event.timestamp}] Session ${event.session.id} waiting`);
      console.log(`  Context: ${event.context.text_preview}`);
      
      // Your orchestration logic here
      await handleWaitingSession(event);
      
    } catch (e) {
      // Skip malformed lines
    }
  }
}

async function handleWaitingSession(event: WaitingEvent) {
  // Example: Inject a response
  // await injectResponse(event.session.id, "Continue with the next step");
  
  // Example: Notify your orchestrator
  // await orchestrator.sessionReady(event.session.id, event.context);
}

// Watch for changes
watch(EVENT_LOG, (eventType) => {
  if (eventType === 'change') {
    processNewEvents();
  }
});

// Initial read
processNewEvents();
console.log(`Watching ${EVENT_LOG} for events...`);
```

-----

## Event Schema

Each event written to `events.jsonl`:

```json
{
  "event": "waiting_for_input",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-01-06T15:30:00-08:00",
  "session": {
    "id": "session-abc123def456",
    "transcript_path": "/Users/you/.claude/projects/myproject/session-abc123def456.jsonl",
    "message_count": 42
  },
  "context": {
    "preceding_text": "I've completed the refactoring. The changes include:\n\n1. Extracted the authentication logic into a separate module\n2. Added proper error handling\n3. Updated the tests\n\nWould you like me to commit these changes?",
    "last_tool": "Edit",
    "text_preview": "I've completed the refactoring. The changes include:\n\n1. Extracted the authentication logic into a separate..."
  }
}
```

-----

## Integration with CBOS

For your TypeScript CBOS rewrite, you’d likely:

1. **Run the hook** to write events
1. **Watch events.jsonl** with `fs.watch()` or chokidar
1. **Parse events** into your session state machine
1. **Trigger responses** via the Claude Agent SDK or `claude -p --continue`

```typescript
// Pseudocode for CBOS integration
class SessionManager {
  private sessions = new Map<string, SessionState>();
  
  onWaitingEvent(event: WaitingEvent) {
    const session = this.sessions.get(event.session.id);
    if (!session) return;
    
    session.status = 'waiting';
    session.lastContext = event.context.preceding_text;
    session.waitingSince = new Date(event.timestamp);
    
    // Emit to your monitoring UI
    this.emit('session:waiting', session);
    
    // If there's a queued task, inject it
    const nextTask = this.taskQueue.pop(session.id);
    if (nextTask) {
      this.injectInput(session.id, nextTask);
    }
  }
}
```

-----

## Summary

|Component           |Purpose                                 |
|--------------------|----------------------------------------|
|`Stop` hook         |Authoritative “waiting for input” signal|
|`transcript_path`   |Access full conversation context        |
|`events.jsonl`      |Durable event log for replay/debugging  |
|`current-state.json`|Quick polling for current status        |
|Named pipe / webhook|Real-time streaming to other processes  |

This gives you reliable detection without screen scraping, full context without losing the TUI experience, and flexible consumption patterns for your orchestration layer.
