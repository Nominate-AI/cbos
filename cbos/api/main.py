"""FastAPI server for CBOS"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..core.store import SessionStore
from ..core.models import (
    Session,
    SessionCreate,
    SendInput,
    SessionStatus,
    StashedResponse,
    WSMessage,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
store: Optional[SessionStore] = None
connected_clients: set[WebSocket] = set()
refresh_task: Optional[asyncio.Task] = None


async def broadcast(message: dict):
    """Broadcast a message to all connected WebSocket clients"""
    dead_clients = set()
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead_clients.add(ws)
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
    global store, refresh_task

    logger.info("Starting CBOS API server")
    store = SessionStore()
    store.sync_with_screen()
    store.refresh_states()

    # Start background refresh task
    refresh_task = asyncio.create_task(refresh_loop())

    yield

    # Cleanup
    logger.info("Shutting down CBOS API server")
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
