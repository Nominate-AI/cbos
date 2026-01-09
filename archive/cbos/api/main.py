"""FastAPI server for CBOS"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..core.store import SessionStore
from ..core.stream import StreamManager
from ..core.json_manager import JSONSessionManager, JSONSessionState, ClaudeEvent
from ..core.models import (
    Session,
    SessionCreate,
    SessionState,
    SendInput,
    InvokeRequest,
    SessionStatus,
    SessionType,
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
json_manager: Optional[JSONSessionManager] = None
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
            # Run blocking subprocess calls in thread to not block event loop
            await asyncio.to_thread(store.sync_with_screen)
            await asyncio.to_thread(store.refresh_states)

            # Check for sessions waiting for input (legacy screen mode)
            waiting = store.waiting()

            # Get ALL sessions (screen + JSON) using the unified list_sessions function
            all_sessions = list_sessions()

            # Broadcast update to all clients
            await broadcast(
                {
                    "type": "refresh",
                    "sessions": [s.model_dump(mode="json") for s in all_sessions],
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


def cleanup_stale_typescript_files(active_slugs: set[str]) -> None:
    """Remove typescript files for sessions that no longer exist"""
    from ..core.config import get_config
    config = get_config()
    stream_dir = config.stream.stream_dir

    for ts_file in stream_dir.glob("*.typescript"):
        slug = ts_file.stem
        if slug not in active_slugs:
            # Remove stale typescript and timing files
            ts_file.unlink()
            timing_file = stream_dir / f"{slug}.timing"
            if timing_file.exists():
                timing_file.unlink()
            logger.info(f"Cleaned up stale typescript files for: {slug}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global store, stream_manager, json_manager, refresh_task, stream_task

    logger.info("Starting CBOS API server")

    # Initialize store
    store = SessionStore()
    store.sync_with_screen()

    # Clean up stale typescript files from dead sessions
    active_slugs = {s.slug for s in store.all()}
    cleanup_stale_typescript_files(active_slugs)

    # Initialize stream manager
    stream_manager = StreamManager()

    # Register stream callback to broadcast to WebSocket clients
    stream_manager.on_stream(connection_manager.broadcast_stream)

    # Initialize JSON session manager
    json_manager = JSONSessionManager()

    # Register JSON event callback to broadcast via WebSocket
    async def broadcast_json_event(slug: str, event: ClaudeEvent):
        await connection_manager.broadcast_json_event(slug, event)

    json_manager.on_event(broadcast_json_event)

    # Register JSON state callback
    async def broadcast_json_state(slug: str, state: JSONSessionState):
        await connection_manager.broadcast_json_state(slug, state)

    json_manager.on_state_change(broadcast_json_state)

    logger.info("JSON session manager initialized")

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
    """List all sessions (both screen and JSON modes)"""
    store.sync_with_screen()
    store.refresh_states()

    # Get screen sessions
    sessions = store.all()

    # Add JSON sessions
    if json_manager:
        for js in json_manager.list_sessions():
            # Map JSON session state to SessionState
            state_map = {
                "idle": SessionState.IDLE,
                "running": SessionState.WORKING,
                "complete": SessionState.IDLE,
                "error": SessionState.ERROR,
            }
            sessions.append(Session(
                slug=js.slug,
                path=js.path,
                session_type=SessionType.JSON,
                state=state_map.get(js.state.value, SessionState.UNKNOWN),
                claude_session_id=js.claude_session_id,
                created_at=js.created_at,
                last_activity=js.last_activity,
            ))

    return sessions


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
    """
    Create a new Claude Code session.

    NOTE: All sessions now use JSON streaming mode. The session_type parameter
    is ignored for backwards compatibility but all sessions are JSON mode.

    JSON mode uses `claude -p --output-format stream-json --resume` for
    structured output instead of screen scraping.
    """
    if not json_manager:
        raise HTTPException(500, "JSON session manager not initialized")

    # Check for existing session
    existing_json = json_manager.get_session(req.slug)
    if existing_json:
        raise HTTPException(400, f"Session '{req.slug}' already exists")

    # DEPRECATED: Screen mode is no longer supported
    # All sessions now use JSON streaming mode
    existing_screen = store.get(req.slug)
    if existing_screen:
        raise HTTPException(400, f"Session '{req.slug}' already exists (legacy screen session)")

    try:
        # Create JSON mode session (this is now the only mode)
        json_session = json_manager.create_session(req.slug, req.path)

        # Map JSON state to SessionState enum
        state_map = {
            "idle": SessionState.IDLE,
            "running": SessionState.WORKING,
            "complete": SessionState.IDLE,
            "error": SessionState.ERROR,
        }

        return Session(
            slug=json_session.slug,
            path=json_session.path,
            session_type=SessionType.JSON,
            state=state_map.get(json_session.state.value, SessionState.IDLE),
            claude_session_id=json_session.claude_session_id,
            created_at=json_session.created_at,
            last_activity=json_session.last_activity,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"Failed to create session {req.slug}")
        raise HTTPException(500, str(e))


@app.delete("/sessions/{slug}")
def delete_session(slug: str):
    """Kill a session (screen or JSON mode)"""
    # Try deleting from screen sessions first
    if store.get(slug):
        if not store.delete(slug):
            raise HTTPException(500, f"Failed to delete session '{slug}'")
        return {"status": "deleted", "slug": slug}

    # Try JSON sessions
    if json_manager and json_manager.get_session(slug):
        if not json_manager.delete_session(slug):
            raise HTTPException(500, f"Failed to delete JSON session '{slug}'")
        return {"status": "deleted", "slug": slug}

    raise HTTPException(404, f"Session '{slug}' not found")


@app.post("/sessions/{slug}/send")
async def send_to_session(slug: str, req: SendInput):
    """Send input to a session (screen: send keystrokes, JSON: invoke)"""
    # Check screen sessions first
    if store.get(slug):
        if not store.send_input(slug, req.text):
            raise HTTPException(500, "Failed to send input")
        return {"status": "sent", "slug": slug}

    # Check JSON sessions - invoke instead of send
    if json_manager and json_manager.get_session(slug):
        session = json_manager.get_session(slug)
        if session.state == JSONSessionState.RUNNING:
            raise HTTPException(400, f"Session '{slug}' is already running")

        # Start invocation in background
        async def run_invocation():
            try:
                async for event in json_manager.invoke(slug, req.text):
                    pass  # Events are broadcast via callback
            except Exception as e:
                logger.error(f"Invocation error for {slug}: {e}")

        asyncio.create_task(run_invocation())
        return {"status": "invoked", "slug": slug}

    raise HTTPException(404, f"Session '{slug}' not found")


@app.post("/sessions/{slug}/interrupt")
async def interrupt_session(slug: str):
    """Send interrupt to a session (screen: Ctrl+C, JSON: terminate)"""
    # Check screen sessions first
    if store.get(slug):
        if not store.send_interrupt(slug):
            raise HTTPException(500, "Failed to send interrupt")
        return {"status": "interrupted", "slug": slug}

    # Check JSON sessions
    if json_manager and json_manager.get_session(slug):
        if await json_manager.interrupt(slug):
            return {"status": "interrupted", "slug": slug}
        raise HTTPException(400, "Session not running")

    raise HTTPException(404, f"Session '{slug}' not found")


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
# JSON Session Endpoints
# ============================================================================


@app.get("/json-sessions")
def list_json_sessions():
    """List all JSON-mode sessions"""
    if not json_manager:
        return []
    return [s.to_dict() for s in json_manager.list_sessions()]


@app.get("/json-sessions/{slug}")
def get_json_session(slug: str):
    """Get a JSON session by slug"""
    if not json_manager:
        raise HTTPException(404, f"JSON session '{slug}' not found")

    session = json_manager.get_session(slug)
    if not session:
        raise HTTPException(404, f"JSON session '{slug}' not found")

    return session.to_dict()


@app.post("/json-sessions/{slug}/invoke")
async def invoke_json_session(slug: str, req: InvokeRequest):
    """
    Invoke Claude on a JSON session.

    This starts an async invocation - events are streamed via WebSocket.
    Returns immediately with invocation status.
    """
    if not json_manager:
        raise HTTPException(500, "JSON session manager not initialized")

    session = json_manager.get_session(slug)
    if not session:
        raise HTTPException(404, f"JSON session '{slug}' not found")

    if session.state == JSONSessionState.RUNNING:
        raise HTTPException(400, f"Session '{slug}' is already running")

    # Start invocation in background
    async def run_invocation():
        try:
            async for event in json_manager.invoke(
                slug,
                req.prompt,
                skip_permissions=req.skip_permissions,
                model=req.model,
                max_turns=req.max_turns,
            ):
                pass  # Events are broadcast via callback
        except Exception as e:
            logger.error(f"Invocation error for {slug}: {e}")

    asyncio.create_task(run_invocation())

    return {"status": "started", "slug": slug}


@app.get("/json-sessions/{slug}/events")
def get_json_events(slug: str, limit: int = 50, event_type: Optional[str] = None):
    """Get recent events for a JSON session"""
    if not json_manager:
        raise HTTPException(404, f"JSON session '{slug}' not found")

    events = json_manager.get_events(slug, limit=limit, event_type=event_type)
    return {"events": [e.to_dict() for e in events]}


@app.post("/json-sessions/{slug}/interrupt")
async def interrupt_json_session(slug: str):
    """Interrupt a running JSON session"""
    if not json_manager:
        raise HTTPException(404, f"JSON session '{slug}' not found")

    if await json_manager.interrupt(slug):
        return {"status": "interrupted", "slug": slug}
    raise HTTPException(400, "Session not running or not found")


@app.delete("/json-sessions/{slug}")
def delete_json_session(slug: str):
    """Delete a JSON session"""
    if not json_manager:
        raise HTTPException(404, f"JSON session '{slug}' not found")

    if not json_manager.delete_session(slug):
        raise HTTPException(404, f"JSON session '{slug}' not found")

    return {"status": "deleted", "slug": slug}


@app.get("/json-sessions/{slug}/last-response")
def get_last_response(slug: str):
    """Get the last assistant response from a JSON session"""
    if not json_manager:
        raise HTTPException(404, f"JSON session '{slug}' not found")

    response = json_manager.get_last_response(slug)
    if response is None:
        raise HTTPException(404, f"No response found for session '{slug}'")

    return {"slug": slug, "response": response}


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
        # Send initial session list (both screen and JSON)
        store.sync_with_screen()
        all_sessions = list_sessions()  # Uses the updated function that includes JSON sessions
        await ws.send_json({
            "type": "sessions",
            "sessions": [s.model_dump(mode="json") for s in all_sessions],
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

                # Send initial snapshot for each subscribed session
                if stream_manager:
                    # Get active session slugs from store
                    active_slugs = {s.slug for s in store.all()}

                    if "*" in subscribed:
                        # Wildcard: send snapshots only for ACTIVE sessions with typescript files
                        available = stream_manager.get_sessions()
                        sessions_to_snapshot = [s for s in available if s in active_slugs]
                    else:
                        # Specific sessions - only if active
                        sessions_to_snapshot = [s for s in subscribed if s != "*" and s in active_slugs]

                    for session_slug in sessions_to_snapshot:
                        # Get current buffer content
                        buffer = await stream_manager.get_buffer(session_slug, max_bytes=100000)
                        if buffer:
                            await ws.send_json({
                                "type": "stream",
                                "session": session_slug,
                                "data": buffer,
                                "ts": time.time(),
                                "snapshot": True,
                            })
                            logger.debug(f"Sent initial snapshot for {session_slug}: {len(buffer)} bytes")

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
                session_slug = data.get("session")
                text = data.get("text")
                if session_slug and text:
                    # Check if it's a JSON session
                    json_session = json_manager.get_session(session_slug) if json_manager else None
                    if json_session:
                        # JSON session: invoke Claude
                        if json_session.state == JSONSessionState.RUNNING:
                            await ws.send_json({
                                "type": "send_result",
                                "session": session_slug,
                                "success": False,
                                "error": "Session is already running",
                            })
                        else:
                            # Start invocation in background
                            async def run_json_invoke(slug: str, prompt: str):
                                try:
                                    async for event in json_manager.invoke(slug, prompt):
                                        pass  # Events broadcast via callback
                                except Exception as e:
                                    logger.error(f"JSON invoke error for {slug}: {e}")

                            asyncio.create_task(run_json_invoke(session_slug, text))
                            await ws.send_json({
                                "type": "send_result",
                                "session": session_slug,
                                "success": True,
                            })
                    else:
                        # Screen session: send keystrokes
                        success = store.send_input(session_slug, text)
                        await ws.send_json({
                            "type": "send_result",
                            "session": session_slug,
                            "success": success,
                        })

            elif msg_type == "interrupt":
                # Send interrupt to a session
                session_slug = data.get("session")
                if session_slug:
                    # Check if it's a JSON session
                    json_session = json_manager.get_session(session_slug) if json_manager else None
                    if json_session:
                        success = await json_manager.interrupt(session_slug)
                    else:
                        success = store.send_interrupt(session_slug)
                    await ws.send_json({
                        "type": "interrupt_result",
                        "session": session_slug,
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
                # Refresh and send session list (both screen and JSON)
                store.sync_with_screen()
                all_sessions = list_sessions()  # Uses the updated list_sessions function
                await ws.send_json({
                    "type": "sessions",
                    "sessions": [s.model_dump(mode="json") for s in all_sessions],
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
