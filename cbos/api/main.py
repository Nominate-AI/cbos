"""FastAPI server for CBOS"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..core.store import SessionStore
from ..core.stream import StreamManager
from ..core.models import (
    Session,
    SessionCreate,
    SendInput,
    SessionStatus,
    StashedResponse,
    WSMessage,
)
from ..core.logging import setup_logging, get_logger
from .websocket import connection_manager

# Initialize logging
setup_logging()
logger = get_logger("api")

# Global state
store: Optional[SessionStore] = None
stream_manager: Optional[StreamManager] = None
connected_clients: set[WebSocket] = set()  # Legacy clients
refresh_task: Optional[asyncio.Task] = None
stream_task: Optional[asyncio.Task] = None


async def broadcast(message: dict):
    """Broadcast a message to all connected WebSocket clients"""
    if not connected_clients:
        return

    dead_clients = set()
    msg_type = message.get("type", "unknown")
    logger.debug(f"Broadcasting '{msg_type}' to {len(connected_clients)} clients")

    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead_clients.add(ws)

    if dead_clients:
        logger.debug(f"Removed {len(dead_clients)} dead clients")
        connected_clients.difference_update(dead_clients)


async def refresh_loop():
    """Periodically refresh session states and notify clients"""
    while True:
        try:
            await asyncio.sleep(2)  # Poll every 2 seconds
            store.sync_with_screen()
            store.refresh_states()

            # Check for sessions waiting for input
            waiting = store.waiting()
            sessions = store.all()

            # Broadcast update to all clients
            await broadcast(
                {
                    "type": "refresh",
                    "sessions": [s.model_dump(mode="json") for s in sessions],
                    "waiting_count": len(waiting),
                }
            )

            # Send alert if there are waiting sessions
            if waiting:
                slugs = [s.slug for s in waiting]
                await broadcast(
                    {
                        "type": "alert",
                        "alert": f"Waiting: {', '.join(slugs)}",
                        "waiting": slugs,
                    }
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in refresh loop: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global store, stream_manager, refresh_task, stream_task

    logger.info("Starting CBOS API server")

    # Initialize store
    store = SessionStore()
    store.sync_with_screen()

    # Initialize stream manager
    stream_manager = StreamManager()

    # Register stream callback to broadcast to WebSocket clients
    stream_manager.on_stream(connection_manager.broadcast_stream)

    # Start stream watcher task
    stream_task = asyncio.create_task(stream_manager.start())
    logger.info("Stream watcher started")

    # Start legacy background refresh task (for session list sync)
    # Note: State heuristics are disabled, this just syncs session list
    refresh_task = asyncio.create_task(refresh_loop())

    yield

    # Cleanup
    logger.info("Shutting down CBOS API server")

    if stream_task:
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass

    if refresh_task:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="CBOS API",
    description="Claude Code Operating System - Session Manager",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# REST Endpoints
# ============================================================================


@app.get("/")
def root():
    """Health check"""
    return {"status": "ok", "service": "cbos"}


@app.get("/sessions", response_model=list[Session])
def list_sessions():
    """List all sessions"""
    store.sync_with_screen()
    store.refresh_states()
    return store.all()


@app.get("/sessions/status", response_model=SessionStatus)
def get_status():
    """Get summary status of all sessions"""
    store.sync_with_screen()
    store.refresh_states()
    return SessionStatus.from_sessions(store.all())


@app.get("/sessions/waiting", response_model=list[Session])
def get_waiting():
    """Get sessions waiting for input"""
    store.sync_with_screen()
    store.refresh_states()
    return store.waiting()


@app.get("/sessions/{slug}", response_model=Session)
def get_session(slug: str):
    """Get a session by slug"""
    session = store.get(slug)
    if not session:
        raise HTTPException(404, f"Session '{slug}' not found")

    # Refresh this session's state
    try:
        buffer = store.get_buffer(slug)
        session.buffer_tail = buffer
        state, question = store.screen.detect_state(buffer)
        session.state = state
        session.last_question = question
    except Exception:
        pass

    return session


@app.post("/sessions", response_model=Session)
def create_session(req: SessionCreate):
    """Create a new Claude Code session"""
    existing = store.get(req.slug)
    if existing:
        raise HTTPException(400, f"Session '{req.slug}' already exists")

    try:
        return store.create(req.slug, req.path)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/sessions/{slug}")
def delete_session(slug: str):
    """Kill a session"""
    if not store.delete(slug):
        raise HTTPException(404, f"Session '{slug}' not found")
    return {"status": "deleted", "slug": slug}


@app.post("/sessions/{slug}/send")
def send_to_session(slug: str, req: SendInput):
    """Send input to a session"""
    if not store.get(slug):
        raise HTTPException(404, f"Session '{slug}' not found")

    if not store.send_input(slug, req.text):
        raise HTTPException(500, "Failed to send input")

    return {"status": "sent", "slug": slug}


@app.post("/sessions/{slug}/interrupt")
def interrupt_session(slug: str):
    """Send Ctrl+C to a session"""
    if not store.get(slug):
        raise HTTPException(404, f"Session '{slug}' not found")

    if not store.send_interrupt(slug):
        raise HTTPException(500, "Failed to send interrupt")

    return {"status": "interrupted", "slug": slug}


@app.get("/sessions/{slug}/buffer")
def get_buffer(slug: str, lines: int = 100):
    """Get the buffer content for a session"""
    if not store.get(slug):
        raise HTTPException(404, f"Session '{slug}' not found")

    try:
        buffer = store.get_buffer(slug, lines)
        return {"slug": slug, "buffer": buffer, "lines": lines}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.put("/sessions/{slug}/path")
def set_session_path(slug: str, path: str):
    """Set the working directory path for a session"""
    if not store.get(slug):
        raise HTTPException(404, f"Session '{slug}' not found")

    store.set_path(slug, path)
    return {"status": "updated", "slug": slug, "path": path}


# ============================================================================
# Stash Endpoints
# ============================================================================


@app.get("/stash", response_model=list[StashedResponse])
def list_stash(session_slug: Optional[str] = None):
    """List stashed responses"""
    return store.list_stash(session_slug)


@app.post("/stash", response_model=StashedResponse)
def create_stash(session_slug: str, question: str, response: str):
    """Stash a response for later"""
    return store.stash_response(session_slug, question, response)


@app.post("/stash/{stash_id}/apply")
def apply_stash(stash_id: str):
    """Apply a stashed response"""
    if not store.apply_stash(stash_id):
        raise HTTPException(404, f"Stash '{stash_id}' not found or failed to apply")
    return {"status": "applied", "stash_id": stash_id}


@app.delete("/stash/{stash_id}")
def delete_stash(stash_id: str):
    """Delete a stashed response"""
    if not store.delete_stash(stash_id):
        raise HTTPException(404, f"Stash '{stash_id}' not found")
    return {"status": "deleted", "stash_id": stash_id}


# ============================================================================
# Intelligence Endpoints
# ============================================================================

from ..intelligence.service import get_intelligence_service
from ..intelligence.models import SuggestionResponse, SummaryResponse, PrioritizedSession


@app.get("/intelligence/health")
async def intelligence_health():
    """Check intelligence service health"""
    service = get_intelligence_service()
    return await service.health_check()


@app.post("/sessions/{slug}/suggest", response_model=SuggestionResponse)
async def suggest_response(slug: str):
    """Generate AI-suggested response for a waiting session"""
    session = store.get(slug)
    if not session:
        raise HTTPException(404, f"Session '{slug}' not found")

    if session.state.value != "waiting":
        raise HTTPException(400, f"Session '{slug}' is not waiting for input (state: {session.state.value})")

    question = session.last_question or ""
    if not question:
        raise HTTPException(400, f"Session '{slug}' has no question to respond to")

    buffer = store.get_buffer(slug, lines=50)

    service = get_intelligence_service()
    suggestion = await service.suggest_response(
        question=question,
        context=buffer,
        session_slug=slug,
    )

    return SuggestionResponse(
        slug=slug,
        question=question,
        suggestion=suggestion,
    )


@app.get("/sessions/{slug}/summary", response_model=SummaryResponse)
async def get_session_summary(slug: str):
    """Get AI-generated summary of session activity"""
    session = store.get(slug)
    if not session:
        raise HTTPException(404, f"Session '{slug}' not found")

    buffer = store.get_buffer(slug, lines=200)

    service = get_intelligence_service()
    summary = await service.summarize_session(
        buffer=buffer,
        session_slug=slug,
    )

    return SummaryResponse(
        slug=slug,
        summary=summary,
    )


@app.get("/sessions/prioritized", response_model=list[PrioritizedSession])
async def get_prioritized_sessions():
    """Get waiting sessions ranked by priority"""
    from datetime import datetime

    store.sync_with_screen()
    store.refresh_states()
    waiting = store.waiting()

    if not waiting:
        return []

    service = get_intelligence_service()
    prioritized = []

    for session in waiting:
        wait_time = int((datetime.now() - session.last_activity).total_seconds())
        buffer = store.get_buffer(session.slug, lines=50)

        priority = await service.calculate_priority(
            question=session.last_question or "",
            context=buffer,
            wait_time_seconds=wait_time,
            session_slug=session.slug,
        )

        prioritized.append(PrioritizedSession(
            slug=session.slug,
            state=session.state.value,
            question=session.last_question,
            priority=priority,
        ))

    # Sort by priority score descending
    prioritized.sort(key=lambda p: p.priority.score, reverse=True)
    return prioritized


@app.get("/sessions/{slug}/related")
async def get_related_sessions(slug: str) -> list:
    """Find sessions working on similar tasks"""
    session = store.get(slug)
    if not session:
        raise HTTPException(404, f"Session '{slug}' not found")

    service = get_intelligence_service()

    # Make sure this session has an embedding
    buffer = store.get_buffer(slug, lines=100)
    if buffer:
        summary = await service.summarize_session(buffer, slug)
        await service.update_session_embedding(
            slug=slug,
            buffer=buffer,
            summary=summary.short,
            topics=summary.topics,
        )

    related = service.find_related_sessions(slug)
    return [r.model_dump() for r in related]


@app.post("/sessions/route")
async def route_task(task: str) -> dict:
    """Suggest which session should handle a task"""
    store.sync_with_screen()
    store.refresh_states()
    sessions = store.all()

    service = get_intelligence_service()

    # Update embeddings for all sessions
    for session in sessions:
        buffer = store.get_buffer(session.slug, lines=100)
        if buffer:
            try:
                summary = await service.summarize_session(buffer, session.slug)
                await service.update_session_embedding(
                    slug=session.slug,
                    buffer=buffer,
                    summary=summary.short,
                    topics=summary.topics,
                )
            except Exception:
                pass

    # Get routing suggestion
    session_data = [
        {"slug": s.slug, "state": s.state.value}
        for s in sessions
    ]

    result = await service.suggest_route(task, session_data)
    return result


# ============================================================================
# WebSocket
# ============================================================================


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await ws.accept()
    connected_clients.add(ws)
    logger.info(f"WebSocket client connected. Total: {len(connected_clients)}")

    try:
        # Send initial state
        store.sync_with_screen()
        store.refresh_states()
        await ws.send_json(
            {
                "type": "init",
                "sessions": [s.model_dump(mode="json") for s in store.all()],
            }
        )

        # Listen for client messages
        while True:
            data = await ws.receive_json()
            msg = WSMessage(**data)

            if msg.type == "send" and msg.slug and msg.text:
                # Send input to session
                success = store.send_input(msg.slug, msg.text)
                await ws.send_json(
                    {
                        "type": "send_result",
                        "slug": msg.slug,
                        "success": success,
                    }
                )

            elif msg.type == "interrupt" and msg.slug:
                # Send interrupt to session
                success = store.send_interrupt(msg.slug)
                await ws.send_json(
                    {
                        "type": "interrupt_result",
                        "slug": msg.slug,
                        "success": success,
                    }
                )

            elif msg.type == "refresh":
                # Force refresh
                store.sync_with_screen()
                store.refresh_states()
                await ws.send_json(
                    {
                        "type": "refresh",
                        "sessions": [s.model_dump(mode="json") for s in store.all()],
                    }
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        connected_clients.discard(ws)
        logger.info(f"WebSocket client disconnected. Total: {len(connected_clients)}")


# ============================================================================
# Streaming WebSocket
# ============================================================================


@app.websocket("/ws/stream")
async def stream_endpoint(ws: WebSocket):
    """
    WebSocket endpoint for real-time session streaming.

    Protocol:
    - Client sends: {"type": "subscribe", "sessions": ["INFRA", "AUTH"]} or ["*"] for all
    - Client sends: {"type": "unsubscribe", "sessions": ["INFRA"]}
    - Client sends: {"type": "send", "session": "INFRA", "text": "yes"}
    - Client sends: {"type": "interrupt", "session": "INFRA"}
    - Server sends: {"type": "stream", "session": "INFRA", "data": "...", "ts": 1234567890.123}
    - Server sends: {"type": "sessions", "sessions": [...]}
    - Server sends: {"type": "subscribed", "sessions": ["INFRA", "AUTH"]}
    """
    client = await connection_manager.connect(ws)
    logger.info(f"Stream client connected. Total: {connection_manager.connection_count}")

    try:
        # Send initial session list
        store.sync_with_screen()
        sessions = [s.model_dump(mode="json") for s in store.all()]
        await ws.send_json({
            "type": "sessions",
            "sessions": sessions,
        })

        # Send available streams (typescript files)
        if stream_manager:
            available = stream_manager.get_sessions()
            await ws.send_json({
                "type": "available_streams",
                "sessions": available,
            })

        # Listen for client messages
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "subscribe":
                # Subscribe to session streams
                sessions_to_sub = data.get("sessions", [])
                subscribed = await connection_manager.subscribe(ws, sessions_to_sub)
                await ws.send_json({
                    "type": "subscribed",
                    "sessions": subscribed,
                })
                logger.debug(f"Client subscribed to: {subscribed}")

            elif msg_type == "unsubscribe":
                # Unsubscribe from session streams
                sessions_to_unsub = data.get("sessions", [])
                remaining = await connection_manager.unsubscribe(ws, sessions_to_unsub)
                await ws.send_json({
                    "type": "subscribed",
                    "sessions": remaining,
                })

            elif msg_type == "send":
                # Send input to a session
                session = data.get("session")
                text = data.get("text")
                if session and text:
                    success = store.send_input(session, text)
                    await ws.send_json({
                        "type": "send_result",
                        "session": session,
                        "success": success,
                    })

            elif msg_type == "interrupt":
                # Send interrupt to a session
                session = data.get("session")
                if session:
                    success = store.send_interrupt(session)
                    await ws.send_json({
                        "type": "interrupt_result",
                        "session": session,
                        "success": success,
                    })

            elif msg_type == "get_buffer":
                # Get current buffer for a session
                session = data.get("session")
                if session and stream_manager:
                    buffer = await stream_manager.get_buffer(session)
                    await ws.send_json({
                        "type": "buffer",
                        "session": session,
                        "data": buffer,
                    })

            elif msg_type == "list_sessions":
                # Refresh and send session list
                store.sync_with_screen()
                sessions = [s.model_dump(mode="json") for s in store.all()]
                await ws.send_json({
                    "type": "sessions",
                    "sessions": sessions,
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Stream WebSocket error: {e}")
    finally:
        await connection_manager.disconnect(ws)
        logger.info(f"Stream client disconnected. Total: {connection_manager.connection_count}")


def run():
    """Entry point for cbos-api command"""
    import uvicorn

    uvicorn.run(
        "cbos.api.main:app",
        host="127.0.0.1",
        port=32205,
        reload=False,
    )


if __name__ == "__main__":
    run()
