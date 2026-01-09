"""Session summarization service"""

import hashlib
import logging
import time
from typing import Optional

from .client import CBAIClient
from .config import settings
from .models import Summary

logger = logging.getLogger(__name__)


SUMMARY_SYSTEM_PROMPT = """Analyze this Claude Code session buffer and provide a concise summary.

The buffer shows a coding assistant working on a task. Extract:
1. What the session is currently working on (1 short sentence)
2. Key topics/technologies involved
3. The most recent action taken

Respond with valid JSON only:
{
  "short": "1-line summary (max 40 chars)",
  "detailed": "2-3 sentence description",
  "topics": ["topic1", "topic2", "topic3"],
  "last_action": "most recent action"
}"""


class SessionSummarizer:
    """Generate and cache session summaries"""

    def __init__(self, client: Optional[CBAIClient] = None):
        self.client = client or CBAIClient()
        self._cache: dict[str, tuple[Summary, float]] = {}
        self.cache_ttl = settings.summary_cache_ttl

    def _hash_buffer(self, buffer: str) -> str:
        """Generate hash for cache invalidation"""
        return hashlib.md5(buffer.encode()).hexdigest()[:12]

    def _get_cached(self, slug: str, buffer_hash: str) -> Optional[Summary]:
        """Get cached summary if valid"""
        if slug not in self._cache:
            return None

        summary, timestamp = self._cache[slug]
        if time.time() - timestamp > self.cache_ttl:
            return None

        if summary.buffer_hash != buffer_hash:
            return None

        return summary

    async def summarize(
        self,
        buffer: str,
        session_slug: Optional[str] = None,
    ) -> Summary:
        """
        Generate a summary of session activity.

        Args:
            buffer: Session buffer content
            session_slug: Session identifier for caching

        Returns:
            Summary with short/detailed descriptions and topics
        """
        buffer_hash = self._hash_buffer(buffer)

        # Check cache
        if session_slug:
            cached = self._get_cached(session_slug, buffer_hash)
            if cached:
                return cached

        # Truncate buffer for API
        truncated = buffer[-4000:] if len(buffer) > 4000 else buffer

        try:
            result = await self.client.chat_json(
                messages=[
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Session: {session_slug or 'unknown'}\n\nBuffer:\n{truncated}"},
                ],
                provider=settings.summary_provider,
                model=settings.summary_model,
                temperature=0.3,
            )

            if "error" in result:
                return self._fallback_summary(buffer, buffer_hash)

            summary = Summary(
                short=result.get("short", "Working...")[:50],
                detailed=result.get("detailed", "Session active"),
                topics=result.get("topics", [])[:5],
                last_action=result.get("last_action", ""),
                buffer_hash=buffer_hash,
            )

            # Cache it
            if session_slug:
                self._cache[session_slug] = (summary, time.time())

            return summary

        except Exception as e:
            logger.error(f"Failed to summarize: {e}")
            return self._fallback_summary(buffer, buffer_hash)

    def _fallback_summary(self, buffer: str, buffer_hash: str) -> Summary:
        """Generate basic summary from buffer patterns"""
        lines = buffer.strip().split("\n")

        # Try to extract last meaningful line
        last_action = ""
        for line in reversed(lines[-10:]):
            line = line.strip()
            if line and not line.startswith(">") and len(line) > 5:
                last_action = line[:100]
                break

        # Simple topic extraction from common patterns
        topics = []
        buffer_lower = buffer.lower()
        if "test" in buffer_lower:
            topics.append("testing")
        if "error" in buffer_lower or "exception" in buffer_lower:
            topics.append("debugging")
        if "git" in buffer_lower:
            topics.append("git")
        if "api" in buffer_lower:
            topics.append("api")
        if "database" in buffer_lower or "sql" in buffer_lower:
            topics.append("database")

        return Summary(
            short="Session active",
            detailed="Unable to generate AI summary",
            topics=topics[:3],
            last_action=last_action,
            buffer_hash=buffer_hash,
        )

    async def summarize_batch(
        self,
        sessions: list[dict],
    ) -> dict[str, Summary]:
        """
        Summarize multiple sessions.

        Args:
            sessions: List of dicts with 'slug' and 'buffer'

        Returns:
            Dict mapping slug to Summary
        """
        results = {}
        for session in sessions:
            slug = session.get("slug", "")
            buffer = session.get("buffer") or session.get("buffer_tail", "")
            if buffer:
                results[slug] = await self.summarize(buffer, slug)
        return results

    def clear_cache(self, slug: Optional[str] = None) -> None:
        """Clear summary cache"""
        if slug:
            self._cache.pop(slug, None)
        else:
            self._cache.clear()
