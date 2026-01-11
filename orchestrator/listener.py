"""WebSocket listener for CBOS session events

Connects to the CBOS WebSocket server and processes question events,
matching them against the pattern store for auto-answering or suggestions.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosed

from .config import settings
from .store import PatternStore

logger = logging.getLogger(__name__)


@dataclass
class QuestionEvent:
    """Parsed question event from WebSocket"""
    slug: str
    question_text: str
    options: list[str]
    context: str
    timestamp: str
    tool_input: Optional[str] = None


@dataclass
class SessionUpdate:
    """Session state update from WebSocket"""
    slug: str
    state: str
    message_count: int
    last_activity: str


class OrchestratorListener:
    """
    Connects to CBOS WebSocket and processes question events.

    Features:
    - Subscribes to all session events
    - Detects AskUserQuestion tool calls
    - Queries pattern store for similar questions
    - Auto-answers high-confidence matches
    - Logs suggestions for medium-confidence matches
    """

    def __init__(
        self,
        ws_url: Optional[str] = None,
        store: Optional[PatternStore] = None,
        auto_answer_threshold: float = None,
        suggestion_threshold: float = None,
        auto_answer_enabled: bool = True,
    ):
        self.ws_url = ws_url or f"ws://localhost:{settings.listener_port}"
        self.store = store
        self.auto_answer_threshold = auto_answer_threshold or settings.auto_answer_threshold
        self.suggestion_threshold = suggestion_threshold or settings.suggestion_threshold
        self.auto_answer_enabled = auto_answer_enabled

        self._ws = None
        self._running = False
        self._reconnect_delay = 2.0
        self._max_reconnect_delay = 30.0

        # Event callbacks
        self.on_connect: Optional[Callable[[], Awaitable[None]]] = None
        self.on_disconnect: Optional[Callable[[], Awaitable[None]]] = None
        self.on_question: Optional[Callable[[QuestionEvent], Awaitable[None]]] = None
        self.on_suggestion: Optional[Callable[[str, str, float], Awaitable[None]]] = None
        self.on_auto_answer: Optional[Callable[[str, str], Awaitable[None]]] = None
        self.on_session_update: Optional[Callable[[SessionUpdate], Awaitable[None]]] = None

    async def connect(self) -> None:
        """Connect to CBOS WebSocket server"""
        # Initialize store if not provided
        if self.store is None:
            self.store = PatternStore()
        self.store.connect()

        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=30,
                ping_timeout=10,
            )

            # Subscribe to all sessions
            await self._ws.send(json.dumps({
                "type": "subscribe",
                "sessions": ["*"]
            }))

            logger.info(f"Connected to CBOS server at {self.ws_url}")

            if self.on_connect:
                await self.on_connect()

            # Reset reconnect delay on successful connection
            self._reconnect_delay = 2.0

        except Exception as e:
            logger.error(f"Failed to connect to {self.ws_url}: {e}")
            raise

    async def listen(self) -> None:
        """Main event loop - process incoming messages"""
        self._running = True

        while self._running:
            try:
                if self._ws is None:
                    await self.connect()

                message = await self._ws.recv()
                await self._handle_message(json.loads(message))

            except ConnectionClosed:
                logger.warning("Connection closed")
                if self.on_disconnect:
                    await self.on_disconnect()

                if self._running:
                    logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * 1.5,
                        self._max_reconnect_delay
                    )
                    self._ws = None

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON message: {e}")

            except Exception as e:
                logger.error(f"Error processing message: {e}")
                await asyncio.sleep(1)

    async def _handle_message(self, msg: dict) -> None:
        """Route incoming messages to handlers"""
        msg_type = msg.get("type")

        if msg_type == "formatted_event":
            await self._handle_formatted_event(msg)
        elif msg_type == "session_update":
            await self._handle_session_update(msg)
        elif msg_type == "session_waiting":
            await self._handle_session_waiting(msg)
        elif msg_type == "sessions":
            await self._handle_sessions_list(msg)
        elif msg_type == "error":
            logger.error(f"Server error: {msg.get('message')}")

    async def _handle_formatted_event(self, msg: dict) -> None:
        """Process formatted events, looking for questions"""
        slug = msg.get("slug")
        event = msg.get("event", {})

        category = event.get("category")
        tool_name = event.get("toolName")

        # Only process question events (AskUserQuestion)
        if category != "question" and tool_name != "AskUserQuestion":
            return

        # Extract question details
        question_text = event.get("summary", "")

        # Try to get full question from details or toolInput
        if event.get("details"):
            question_text = event.get("details")
        elif event.get("toolInput"):
            try:
                tool_input = json.loads(event.get("toolInput", "{}"))
                if "question" in tool_input:
                    question_text = tool_input["question"]
            except json.JSONDecodeError:
                pass

        question_event = QuestionEvent(
            slug=slug,
            question_text=question_text,
            options=event.get("questionOptions", []),
            context=event.get("details", ""),
            timestamp=event.get("timestamp", ""),
            tool_input=event.get("toolInput"),
        )

        logger.info(f"[{slug}] Question detected: {question_event.question_text[:60]}...")

        # Notify callback
        if self.on_question:
            await self.on_question(question_event)

        # Query pattern store for similar questions
        await self._find_and_respond(slug, question_event)

    async def _handle_session_update(self, msg: dict) -> None:
        """Handle session state updates"""
        session = msg.get("session", {})

        update = SessionUpdate(
            slug=session.get("slug", ""),
            state=session.get("state", "unknown"),
            message_count=session.get("messageCount", 0),
            last_activity=session.get("lastActivity", ""),
        )

        if self.on_session_update:
            await self.on_session_update(update)

    async def _handle_session_waiting(self, msg: dict) -> None:
        """Handle session entering waiting state"""
        slug = msg.get("slug")
        context = msg.get("context", "")
        logger.debug(f"[{slug}] Session waiting for input: {context[:60]}...")

    async def _handle_sessions_list(self, msg: dict) -> None:
        """Handle initial sessions list"""
        sessions = msg.get("sessions", [])
        logger.info(f"Received {len(sessions)} active sessions")

        for session in sessions:
            slug = session.get("slug")
            state = session.get("state")
            logger.debug(f"  [{slug}] state={state}")

    async def _find_and_respond(self, slug: str, event: QuestionEvent) -> None:
        """Find similar patterns and potentially respond"""
        if not self.store:
            return

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
                f"[{slug}] Found match: {similarity:.1%} similar | "
                f"Answer: {suggested_answer[:40]}..."
            )

            # High confidence: auto-answer
            if similarity >= self.auto_answer_threshold and self.auto_answer_enabled:
                logger.info(f"[{slug}] Auto-answering (confidence: {similarity:.1%})")

                if self.on_auto_answer:
                    await self.on_auto_answer(slug, suggested_answer)

                await self._send_answer(slug, suggested_answer)

            # Medium confidence: suggest
            elif similarity >= self.suggestion_threshold:
                logger.info(f"[{slug}] Suggestion (confidence: {similarity:.1%}): {suggested_answer}")

                if self.on_suggestion:
                    await self.on_suggestion(slug, suggested_answer, similarity)

        except Exception as e:
            logger.error(f"[{slug}] Error querying patterns: {e}")

    async def _send_answer(self, slug: str, answer: str) -> None:
        """Send auto-answer to session via WebSocket"""
        if not self._ws:
            logger.warning(f"[{slug}] Cannot send answer - not connected")
            return

        # Ensure answer ends with newline
        if not answer.endswith("\n"):
            answer = answer + "\n"

        await self._ws.send(json.dumps({
            "type": "send_input",
            "slug": slug,
            "text": answer
        }))

        logger.info(f"[{slug}] Sent answer: {answer.strip()}")

    async def stop(self) -> None:
        """Stop the listener gracefully"""
        self._running = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self.store:
            self.store.close()

        logger.info("Listener stopped")

    async def close(self) -> None:
        """Alias for stop()"""
        await self.stop()


async def run_listener(
    ws_url: str = None,
    auto_answer_threshold: float = None,
    suggestion_threshold: float = None,
    auto_answer_enabled: bool = True,
    verbose: bool = False,
) -> None:
    """
    Convenience function to run the listener.

    Args:
        ws_url: WebSocket URL (default: ws://localhost:32205)
        auto_answer_threshold: Confidence for auto-answering (default: 0.95)
        suggestion_threshold: Confidence for suggestions (default: 0.80)
        auto_answer_enabled: Whether to auto-answer (default: True)
        verbose: Enable debug logging
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    listener = OrchestratorListener(
        ws_url=ws_url,
        auto_answer_threshold=auto_answer_threshold,
        suggestion_threshold=suggestion_threshold,
        auto_answer_enabled=auto_answer_enabled,
    )

    try:
        await listener.connect()
        await listener.listen()
    except KeyboardInterrupt:
        pass
    finally:
        await listener.close()
