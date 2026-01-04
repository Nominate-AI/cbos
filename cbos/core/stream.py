"""Streaming transport layer for real-time session output"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable

import aiofiles
import watchfiles

from .logging import get_logger
from .config import get_config

logger = get_logger("stream")


@dataclass
class StreamEvent:
    """Event emitted when new content is available from a session"""

    session: str
    data: str
    timestamp: float = field(default_factory=time.time)


class StreamManager:
    """
    Manages real-time streaming of session output.

    Watches typescript files created by `script -f` and emits
    StreamEvents when new content arrives.
    """

    def __init__(self, stream_dir: Path | None = None):
        config = get_config()
        self.stream_dir = stream_dir or config.stream.stream_dir
        self.stream_dir.mkdir(parents=True, exist_ok=True)

        # Track file positions (byte offsets) per session
        self._positions: dict[str, int] = {}

        # Registered callbacks for stream events
        self._callbacks: list[Callable[[StreamEvent], Awaitable[None]]] = []

        # Track active sessions
        self._sessions: set[str] = set()

        # Watch task
        self._watch_task: asyncio.Task | None = None
        self._running = False

        logger.info(f"StreamManager initialized with dir: {self.stream_dir}")

    def typescript_path(self, slug: str) -> Path:
        """Get the typescript file path for a session"""
        return self.stream_dir / f"{slug}.typescript"

    def timing_path(self, slug: str) -> Path:
        """Get the timing file path for a session"""
        return self.stream_dir / f"{slug}.timing"

    def register_session(self, slug: str) -> None:
        """Register a new session for streaming"""
        self._sessions.add(slug)
        self._positions[slug] = 0
        logger.debug(f"Registered session for streaming: {slug}")

    def unregister_session(self, slug: str) -> None:
        """Unregister a session from streaming"""
        self._sessions.discard(slug)
        self._positions.pop(slug, None)
        logger.debug(f"Unregistered session from streaming: {slug}")

    def on_stream(self, callback: Callable[[StreamEvent], Awaitable[None]]) -> None:
        """Register a callback to receive stream events"""
        self._callbacks.append(callback)
        logger.debug(f"Registered stream callback, total: {len(self._callbacks)}")

    async def start(self) -> None:
        """Start watching for file changes"""
        if self._running:
            logger.warning("StreamManager already running")
            return

        self._running = True
        logger.info(f"Starting file watcher on {self.stream_dir}")

        # Initialize positions for existing typescript files
        for ts_file in self.stream_dir.glob("*.typescript"):
            slug = ts_file.stem
            if slug not in self._positions:
                # Start from end of existing files (don't replay history)
                self._positions[slug] = ts_file.stat().st_size
                self._sessions.add(slug)
                logger.debug(f"Found existing typescript: {slug} at position {self._positions[slug]}")

        try:
            logger.debug(f"Starting watchfiles on {self.stream_dir}")
            async for changes in watchfiles.awatch(
                self.stream_dir,
                watch_filter=lambda change, path: path.endswith('.typescript'),
                poll_delay_ms=100,  # Check every 100ms for low latency
                debounce=500,  # Reduce from default 1600ms for faster response
                force_polling=True,  # More reliable under systemd than inotify
            ):
                logger.debug(f"File changes detected: {len(changes)}")
                if not self._running:
                    break

                for change_type, path_str in changes:
                    path = Path(path_str)
                    if path.suffix == '.typescript':
                        await self._handle_change(path)

        except asyncio.CancelledError:
            logger.info("File watcher cancelled")
        except Exception as e:
            logger.error(f"File watcher error: {e}")
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the file watcher"""
        self._running = False
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            self._watch_task = None

    async def _handle_change(self, path: Path) -> None:
        """Handle a change to a typescript file"""
        slug = path.stem

        # Get current position
        pos = self._positions.get(slug, 0)

        try:
            # Read new content from current position
            async with aiofiles.open(path, 'rb') as f:
                await f.seek(pos)
                new_data = await f.read()

            if not new_data:
                return

            # Update position
            new_pos = pos + len(new_data)
            self._positions[slug] = new_pos

            # Decode and emit event
            try:
                text = new_data.decode('utf-8', errors='replace')
            except Exception:
                text = new_data.decode('latin-1', errors='replace')

            event = StreamEvent(session=slug, data=text)
            logger.debug(f"[{slug}] Stream event: {len(text)} chars")

            # Notify all callbacks
            await self._emit(event)

        except FileNotFoundError:
            # File was deleted
            logger.debug(f"[{slug}] Typescript file deleted")
            self._positions.pop(slug, None)
        except Exception as e:
            logger.error(f"[{slug}] Error reading typescript: {e}")

    async def _emit(self, event: StreamEvent) -> None:
        """Emit a stream event to all registered callbacks"""
        for callback in self._callbacks:
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def get_buffer(self, slug: str, max_bytes: int = 10000) -> str:
        """Get the current buffer content for a session"""
        path = self.typescript_path(slug)

        if not path.exists():
            return ""

        try:
            async with aiofiles.open(path, 'rb') as f:
                # Seek to end - max_bytes
                await f.seek(0, 2)  # Seek to end
                size = await f.tell()

                if size > max_bytes:
                    await f.seek(size - max_bytes)
                else:
                    await f.seek(0)

                data = await f.read()
                return data.decode('utf-8', errors='replace')

        except Exception as e:
            logger.error(f"[{slug}] Error reading buffer: {e}")
            return ""

    def get_sessions(self) -> list[str]:
        """Get list of sessions with typescript files"""
        sessions = []
        for ts_file in self.stream_dir.glob("*.typescript"):
            sessions.append(ts_file.stem)
        return sessions
