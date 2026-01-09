"""WebSocket streaming infrastructure for CBOS"""

import asyncio
import time
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass, field

from fastapi import WebSocket

from ..core.stream import StreamEvent
from ..core.logging import get_logger

if TYPE_CHECKING:
    from ..core.json_manager import ClaudeEvent, JSONSessionState

logger = get_logger("websocket")


@dataclass
class ClientConnection:
    """Represents a connected WebSocket client"""

    websocket: WebSocket
    subscriptions: set[str] = field(default_factory=set)
    subscribe_all: bool = False


class ConnectionManager:
    """
    Manages WebSocket connections and streaming subscriptions.

    Clients can subscribe to specific sessions or all sessions.
    Stream events are broadcast only to subscribed clients.
    """

    def __init__(self):
        # Map of WebSocket -> ClientConnection
        self._connections: dict[WebSocket, ClientConnection] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> ClientConnection:
        """Accept and register a new WebSocket connection"""
        await websocket.accept()

        async with self._lock:
            client = ClientConnection(websocket=websocket)
            self._connections[websocket] = client

        logger.info(f"Client connected. Total: {len(self._connections)}")
        return client

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection"""
        async with self._lock:
            self._connections.pop(websocket, None)

        logger.info(f"Client disconnected. Total: {len(self._connections)}")

    async def subscribe(
        self, websocket: WebSocket, sessions: list[str]
    ) -> list[str]:
        """
        Subscribe a client to session streams.

        Args:
            websocket: The client's WebSocket
            sessions: List of session slugs, or ["*"] for all

        Returns:
            List of subscribed sessions
        """
        async with self._lock:
            client = self._connections.get(websocket)
            if not client:
                return []

            if "*" in sessions:
                client.subscribe_all = True
                client.subscriptions.clear()
                logger.debug(f"Client subscribed to all sessions")
                return ["*"]
            else:
                client.subscribe_all = False
                client.subscriptions.update(sessions)
                logger.debug(f"Client subscribed to: {sessions}")
                return list(client.subscriptions)

    async def unsubscribe(
        self, websocket: WebSocket, sessions: list[str]
    ) -> list[str]:
        """
        Unsubscribe a client from session streams.

        Args:
            websocket: The client's WebSocket
            sessions: List of session slugs to unsubscribe from

        Returns:
            List of remaining subscriptions
        """
        async with self._lock:
            client = self._connections.get(websocket)
            if not client:
                return []

            if "*" in sessions:
                client.subscribe_all = False
                client.subscriptions.clear()
            else:
                client.subscriptions.difference_update(sessions)

            return list(client.subscriptions)

    async def broadcast_stream(self, event: StreamEvent) -> None:
        """
        Broadcast a stream event to subscribed clients.

        Args:
            event: The StreamEvent to broadcast
        """
        if not self._connections:
            return

        message = {
            "type": "stream",
            "session": event.session,
            "data": event.data,
            "ts": event.timestamp,
        }

        dead_clients: list[WebSocket] = []

        async with self._lock:
            clients = list(self._connections.items())

        for websocket, client in clients:
            # Check if client is subscribed to this session
            if not client.subscribe_all and event.session not in client.subscriptions:
                continue

            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send to client: {e}")
                dead_clients.append(websocket)

        # Clean up dead clients
        if dead_clients:
            async with self._lock:
                for ws in dead_clients:
                    self._connections.pop(ws, None)
            logger.debug(f"Removed {len(dead_clients)} dead clients")

    async def broadcast_sessions(self, sessions: list[dict]) -> None:
        """
        Broadcast session list to all connected clients.

        Args:
            sessions: List of session dictionaries
        """
        if not self._connections:
            return

        message = {
            "type": "sessions",
            "sessions": sessions,
        }

        dead_clients: list[WebSocket] = []

        async with self._lock:
            clients = list(self._connections.keys())

        for websocket in clients:
            try:
                await websocket.send_json(message)
            except Exception:
                dead_clients.append(websocket)

        # Clean up dead clients
        if dead_clients:
            async with self._lock:
                for ws in dead_clients:
                    self._connections.pop(ws, None)

    async def broadcast_json_event(self, slug: str, event: "ClaudeEvent") -> None:
        """
        Broadcast a JSON Claude event to subscribed clients.

        Args:
            slug: Session identifier
            event: The ClaudeEvent to broadcast
        """
        if not self._connections:
            return

        message = {
            "type": "claude_event",
            "session": slug,
            "event": event.to_dict(),
            "ts": time.time(),
        }

        dead_clients: list[WebSocket] = []

        async with self._lock:
            clients = list(self._connections.items())

        for websocket, client in clients:
            # Check if client is subscribed to this session
            if not client.subscribe_all and slug not in client.subscriptions:
                continue

            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send JSON event to client: {e}")
                dead_clients.append(websocket)

        # Clean up dead clients
        if dead_clients:
            async with self._lock:
                for ws in dead_clients:
                    self._connections.pop(ws, None)
            logger.debug(f"Removed {len(dead_clients)} dead clients")

    async def broadcast_json_state(self, slug: str, state: "JSONSessionState") -> None:
        """
        Broadcast a JSON session state change to subscribed clients.

        Args:
            slug: Session identifier
            state: The new session state
        """
        if not self._connections:
            return

        message = {
            "type": "json_state",
            "session": slug,
            "state": state.value,
            "ts": time.time(),
        }

        dead_clients: list[WebSocket] = []

        async with self._lock:
            clients = list(self._connections.items())

        for websocket, client in clients:
            # Check if client is subscribed to this session
            if not client.subscribe_all and slug not in client.subscriptions:
                continue

            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send JSON state to client: {e}")
                dead_clients.append(websocket)

        # Clean up dead clients
        if dead_clients:
            async with self._lock:
                for ws in dead_clients:
                    self._connections.pop(ws, None)

    async def send_to_client(
        self, websocket: WebSocket, message: dict
    ) -> bool:
        """
        Send a message to a specific client.

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.debug(f"Failed to send to client: {e}")
            return False

    @property
    def connection_count(self) -> int:
        """Number of connected clients"""
        return len(self._connections)

    def get_subscriptions(self, websocket: WebSocket) -> Optional[set[str]]:
        """Get subscriptions for a specific client"""
        client = self._connections.get(websocket)
        if not client:
            return None
        if client.subscribe_all:
            return {"*"}
        return client.subscriptions.copy()


# Global connection manager instance
connection_manager = ConnectionManager()
