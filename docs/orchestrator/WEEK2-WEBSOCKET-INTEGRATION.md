# Week 2: WebSocket Integration Plan

## Overview

Instead of building MCP/Agent/Router from scratch, we'll integrate the orchestrator as a WebSocket client to the existing CBOS server infrastructure.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Existing CBOS System                         │
│  ┌──────────────────┐   ┌──────────────────────────────────┐   │
│  │  Claude Sessions │──▶│  WebSocket Server (port 32205)   │   │
│  │  (node-pty)      │   │  - Broadcasts formatted_event    │   │
│  └──────────────────┘   │  - Tracks session state          │   │
│                         └────────────────┬─────────────────┘   │
│                                          │                      │
│                         ┌────────────────┼────────────────┐    │
│                         ▼                ▼                ▼    │
│                    ┌────────┐      ┌─────────┐     ┌─────────┐ │
│                    │  TUI   │      │ Client2 │     │ Client3 │ │
│                    └────────┘      └─────────┘     └─────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                          │
                                          │ NEW: Orchestrator as client
                                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Orchestrator Listener                         │
│  ┌──────────────────┐                                           │
│  │  WebSocket Client │◀─── ws://localhost:32205                 │
│  │  (Python/asyncio) │                                          │
│  └────────┬─────────┘                                           │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐   ┌──────────────────────────────────┐   │
│  │  Event Processor │──▶│  Pattern Store (SQLite + vectl)  │   │
│  │  - Filter events │   │  - query_similar_text()          │   │
│  │  - Detect questions│  │  - Match historical patterns     │   │
│  └──────────┬───────┘   └──────────────────────────────────┘   │
│             │                                                    │
│             ▼                                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Response Handler                                         │  │
│  │  - High confidence → Auto-answer via send_input          │  │
│  │  - Medium confidence → Log suggestion                    │  │
│  │  - Low/no match → Record for learning                    │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Key Integration Points

### 1. WebSocket Message Types (from server)

| Message Type | Use for Orchestrator |
|--------------|---------------------|
| `formatted_event` | Main event stream - detect `question` category |
| `session_update` | Track session state (waiting = question pending) |
| `session_waiting` | Triggered when Claude waits for input |
| `sessions` | Initial session list on connect |

### 2. FormattedEvent Structure

```typescript
interface FormattedEvent {
  category: 'question' | 'tool_use' | 'thinking' | ...;
  summary: string;           // "AskUserQuestion: Which approach...?"
  details?: string;          // Full question text
  questionOptions?: string[]; // Available options
  toolName?: string;         // 'AskUserQuestion'
  toolInput?: string;        // Question JSON
  timestamp: string;
  isActionable: boolean;
}
```

### 3. Client → Server Messages

| Message Type | Purpose |
|--------------|---------|
| `subscribe` | Subscribe to all sessions: `{ sessions: ['*'] }` |
| `send_input` | Auto-answer: `{ slug, text }` |

## Implementation Plan

### File: `orchestrator/listener.py`

```python
"""WebSocket listener for CBOS session events"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

import websockets

from .store import PatternStore
from .models import DecisionPattern

logger = logging.getLogger(__name__)

@dataclass
class QuestionEvent:
    """Parsed question event from WebSocket"""
    slug: str
    question_text: str
    options: list[str]
    context: str
    timestamp: str

class OrchestratorListener:
    """Connects to CBOS WebSocket and processes question events"""

    def __init__(
        self,
        ws_url: str = "ws://localhost:32205",
        store: Optional[PatternStore] = None,
        auto_answer_threshold: float = 0.95,
        suggestion_threshold: float = 0.80,
    ):
        self.ws_url = ws_url
        self.store = store or PatternStore()
        self.auto_answer_threshold = auto_answer_threshold
        self.suggestion_threshold = suggestion_threshold
        self._ws = None
        self._running = False

        # Callbacks
        self.on_question: Optional[Callable[[QuestionEvent], Awaitable[None]]] = None
        self.on_suggestion: Optional[Callable[[str, str, float], Awaitable[None]]] = None
        self.on_auto_answer: Optional[Callable[[str, str], Awaitable[None]]] = None

    async def connect(self) -> None:
        """Connect to CBOS WebSocket server"""
        self.store.connect()
        self._ws = await websockets.connect(self.ws_url)

        # Subscribe to all sessions
        await self._ws.send(json.dumps({
            "type": "subscribe",
            "sessions": ["*"]
        }))

        logger.info(f"Connected to CBOS server at {self.ws_url}")

    async def listen(self) -> None:
        """Main event loop - process incoming messages"""
        self._running = True

        while self._running:
            try:
                message = await self._ws.recv()
                await self._handle_message(json.loads(message))
            except websockets.ConnectionClosed:
                logger.warning("Connection closed, reconnecting...")
                await asyncio.sleep(2)
                await self.connect()
            except Exception as e:
                logger.error(f"Error processing message: {e}")

    async def _handle_message(self, msg: dict) -> None:
        """Route incoming messages to handlers"""
        msg_type = msg.get("type")

        if msg_type == "formatted_event":
            await self._handle_formatted_event(msg)
        elif msg_type == "session_waiting":
            await self._handle_session_waiting(msg)

    async def _handle_formatted_event(self, msg: dict) -> None:
        """Process formatted events, looking for questions"""
        slug = msg.get("slug")
        event = msg.get("event", {})

        # Only process question events
        if event.get("category") != "question":
            return

        if event.get("toolName") != "AskUserQuestion":
            return

        # Extract question details
        question_event = QuestionEvent(
            slug=slug,
            question_text=event.get("summary", ""),
            options=event.get("questionOptions", []),
            context=event.get("details", ""),
            timestamp=event.get("timestamp", ""),
        )

        logger.info(f"[{slug}] Question detected: {question_event.question_text[:60]}...")

        # Notify callback
        if self.on_question:
            await self.on_question(question_event)

        # Query pattern store for similar questions
        await self._find_and_respond(slug, question_event)

    async def _handle_session_waiting(self, msg: dict) -> None:
        """Handle session entering waiting state"""
        slug = msg.get("slug")
        context = msg.get("context", "")
        logger.debug(f"[{slug}] Session waiting for input")

    async def _find_and_respond(self, slug: str, event: QuestionEvent) -> None:
        """Find similar patterns and potentially respond"""
        try:
            matches = await self.store.query_similar_text(
                query_text=event.question_text,
                threshold=self.suggestion_threshold,
                max_results=5,
            )

            if not matches:
                logger.debug(f"[{slug}] No similar patterns found")
                return

            best_match = matches[0]
            similarity = best_match.similarity
            suggested_answer = best_match.pattern.user_answer

            logger.info(
                f"[{slug}] Found match: {similarity:.1%} similar, "
                f"suggested answer: {suggested_answer[:40]}..."
            )

            # High confidence: auto-answer
            if similarity >= self.auto_answer_threshold:
                if self.on_auto_answer:
                    await self.on_auto_answer(slug, suggested_answer)
                await self._send_answer(slug, suggested_answer)

            # Medium confidence: suggest
            elif similarity >= self.suggestion_threshold:
                if self.on_suggestion:
                    await self.on_suggestion(slug, suggested_answer, similarity)

        except Exception as e:
            logger.error(f"[{slug}] Error querying patterns: {e}")

    async def _send_answer(self, slug: str, answer: str) -> None:
        """Send auto-answer to session"""
        if not self._ws:
            return

        await self._ws.send(json.dumps({
            "type": "send_input",
            "slug": slug,
            "text": answer + "\n"
        }))

        logger.info(f"[{slug}] Auto-answered: {answer}")

    async def close(self) -> None:
        """Clean shutdown"""
        self._running = False
        if self._ws:
            await self._ws.close()
        self.store.close()
```

### File: `orchestrator/cli.py` (add `listen` command)

```python
# Add to existing CLI

async def cmd_listen(args):
    """Listen to CBOS sessions and match patterns"""
    from .listener import OrchestratorListener

    console.print("[bold blue]Starting orchestrator listener...[/bold blue]")
    console.print(f"Connecting to: ws://localhost:{args.port}")
    console.print(f"Auto-answer threshold: {args.auto_threshold:.0%}")
    console.print(f"Suggestion threshold: {args.suggest_threshold:.0%}")

    listener = OrchestratorListener(
        ws_url=f"ws://localhost:{args.port}",
        auto_answer_threshold=args.auto_threshold,
        suggestion_threshold=args.suggest_threshold,
    )

    # Set up callbacks for logging
    async def on_question(event):
        console.print(f"[cyan][{event.slug}][/cyan] Question: {event.question_text[:60]}...")

    async def on_suggestion(slug, answer, similarity):
        console.print(
            f"[yellow][{slug}][/yellow] Suggestion ({similarity:.0%}): {answer[:40]}..."
        )

    async def on_auto_answer(slug, answer):
        console.print(f"[green][{slug}][/green] Auto-answered: {answer}")

    listener.on_question = on_question
    listener.on_suggestion = on_suggestion
    listener.on_auto_answer = on_auto_answer

    try:
        await listener.connect()
        await listener.listen()
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
    finally:
        await listener.close()

# Add parser
listen_parser = subparsers.add_parser("listen", help="Listen to CBOS sessions")
listen_parser.add_argument(
    "-p", "--port", type=int, default=32205,
    help="CBOS WebSocket port (default: 32205)"
)
listen_parser.add_argument(
    "--auto-threshold", type=float, default=0.95,
    help="Similarity threshold for auto-answering (default: 0.95)"
)
listen_parser.add_argument(
    "--suggest-threshold", type=float, default=0.80,
    help="Similarity threshold for suggestions (default: 0.80)"
)
```

## Usage

```bash
# Terminal 1: Start CBOS server (if not running)
cd ts && pnpm run server

# Terminal 2: Start orchestrator listener
source ~/.pyenv/versions/tinymachines/bin/activate
cbos-patterns listen

# Output:
# Starting orchestrator listener...
# Connecting to: ws://localhost:32205
# Auto-answer threshold: 95%
# Suggestion threshold: 80%
# [AUTH] Question: Which authentication method should we use?
# [AUTH] Suggestion (87%): Use JWT with refresh tokens
# [BACKEND] Question: Should I proceed with this refactor?
# [BACKEND] Auto-answered: Yes, proceed with the refactor
```

## Benefits Over MCP/Agent/Router

| Aspect | MCP/Agent/Router | WebSocket Integration |
|--------|------------------|----------------------|
| Complexity | High (new protocol) | Low (existing infra) |
| Development time | Weeks | Days |
| Integration | Custom adapters | Native client |
| Real-time events | Need to build | Already streaming |
| Session management | Need to build | Already works |
| Bi-directional | Need to implement | send_input ready |

## Implementation Tasks

1. **`orchestrator/listener.py`** - WebSocket client + event processor
2. **Update `orchestrator/cli.py`** - Add `listen` command
3. **Update `orchestrator/config.py`** - Add listener settings
4. **Add `websockets` dependency** - `pip install websockets`
5. **Test with live sessions** - Run TUI + listener together

## Future Enhancements

1. **Pattern Recording**: Automatically record new question/answer pairs
2. **Confidence Display**: Show match confidence in TUI
3. **Learning Mode**: Flag incorrect auto-answers for retraining
4. **Multi-session Coordination**: Cross-session pattern matching
5. **Custom Message Types**: Extend server to broadcast `pattern_matched` events
