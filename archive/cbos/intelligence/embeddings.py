"""Session embeddings for cross-session context matching"""

import logging
import math
from typing import Optional

from .client import CBAIClient
from .config import settings
from .models import RelatedSession

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors"""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class SessionEmbeddingStore:
    """Store and query session context embeddings"""

    def __init__(self, client: Optional[CBAIClient] = None):
        self.client = client or CBAIClient()
        self._embeddings: dict[str, list[float]] = {}
        self._summaries: dict[str, str] = {}
        self._topics: dict[str, list[str]] = {}

    async def update(
        self,
        slug: str,
        buffer: str,
        summary: Optional[str] = None,
        topics: Optional[list[str]] = None,
    ) -> None:
        """
        Update embedding for a session's current context.

        Args:
            slug: Session identifier
            buffer: Current buffer content
            summary: Pre-computed summary (optional)
            topics: Pre-computed topics (optional)
        """
        # Use summary if provided, otherwise use truncated buffer
        text_to_embed = summary or buffer[-2000:]

        try:
            embedding = await self.client.embed(text_to_embed)

            if isinstance(embedding, list) and len(embedding) > 0:
                # Handle both single embedding and list of embeddings
                if isinstance(embedding[0], list):
                    embedding = embedding[0]

                self._embeddings[slug] = embedding
                self._summaries[slug] = summary or text_to_embed[:500]

                if topics:
                    self._topics[slug] = topics

        except Exception as e:
            logger.error(f"Failed to update embedding for {slug}: {e}")

    def find_related(
        self,
        slug: str,
        threshold: float = None,
        max_results: int = 5,
    ) -> list[RelatedSession]:
        """
        Find sessions with similar context.

        Args:
            slug: Target session to find related sessions for
            threshold: Minimum similarity threshold (default from config)
            max_results: Maximum number of results

        Returns:
            List of related sessions sorted by similarity
        """
        threshold = threshold or settings.related_session_threshold

        if slug not in self._embeddings:
            return []

        target_embedding = self._embeddings[slug]
        target_topics = set(self._topics.get(slug, []))

        related = []
        for other_slug, other_embedding in self._embeddings.items():
            if other_slug == slug:
                continue

            similarity = cosine_similarity(target_embedding, other_embedding)

            if similarity >= threshold:
                other_topics = set(self._topics.get(other_slug, []))
                shared = list(target_topics & other_topics)

                related.append(RelatedSession(
                    slug=other_slug,
                    similarity=round(similarity, 3),
                    context_summary=self._summaries.get(other_slug, ""),
                    shared_topics=shared,
                ))

        # Sort by similarity descending
        related.sort(key=lambda r: r.similarity, reverse=True)
        return related[:max_results]

    def find_similar_to_text(
        self,
        text: str,
        embedding: list[float],
        threshold: float = None,
        max_results: int = 5,
    ) -> list[RelatedSession]:
        """
        Find sessions similar to arbitrary text/embedding.

        Useful for task routing.

        Args:
            text: Description text (for context)
            embedding: Pre-computed embedding
            threshold: Minimum similarity
            max_results: Maximum results

        Returns:
            List of matching sessions
        """
        threshold = threshold or settings.routing_match_threshold

        matches = []
        for slug, session_embedding in self._embeddings.items():
            similarity = cosine_similarity(embedding, session_embedding)

            if similarity >= threshold:
                matches.append(RelatedSession(
                    slug=slug,
                    similarity=round(similarity, 3),
                    context_summary=self._summaries.get(slug, ""),
                    shared_topics=self._topics.get(slug, []),
                ))

        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:max_results]

    def get_embedding(self, slug: str) -> Optional[list[float]]:
        """Get stored embedding for a session"""
        return self._embeddings.get(slug)

    def get_summary(self, slug: str) -> str:
        """Get stored summary for a session"""
        return self._summaries.get(slug, "")

    def get_topics(self, slug: str) -> list[str]:
        """Get stored topics for a session"""
        return self._topics.get(slug, [])

    def remove(self, slug: str) -> None:
        """Remove a session from the store"""
        self._embeddings.pop(slug, None)
        self._summaries.pop(slug, None)
        self._topics.pop(slug, None)

    def clear(self) -> None:
        """Clear all embeddings"""
        self._embeddings.clear()
        self._summaries.clear()
        self._topics.clear()

    @property
    def session_count(self) -> int:
        """Number of sessions with embeddings"""
        return len(self._embeddings)

    def all_slugs(self) -> list[str]:
        """Get all session slugs with embeddings"""
        return list(self._embeddings.keys())
