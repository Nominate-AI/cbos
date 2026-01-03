"""Main intelligence service - coordinates all AI features"""

import logging
from typing import Optional

from .client import CBAIClient
from .config import settings
from .models import Suggestion, Summary, Priority, RelatedSession, RoutingCandidate
from .suggestions import SuggestionGenerator
from .summarizer import SessionSummarizer
from .priority import PriorityCalculator
from .embeddings import SessionEmbeddingStore

logger = logging.getLogger(__name__)


class IntelligenceService:
    """
    Unified intelligence service for CBOS.

    Provides AI-powered features:
    - Response suggestions
    - Session summarization
    - Priority calculation
    - Cross-session context (embeddings)
    - Smart routing
    """

    def __init__(self, cbai_url: Optional[str] = None):
        self.client = CBAIClient(cbai_url)

        # Feature modules
        self.suggestions = SuggestionGenerator(self.client)
        self.summarizer = SessionSummarizer(self.client)
        self.priority = PriorityCalculator(self.client)
        self.embeddings = SessionEmbeddingStore(self.client)

    async def health_check(self) -> dict:
        """Check health of intelligence service and CBAI"""
        cbai_health = await self.client.health()
        return {
            "intelligence": "ok",
            "cbai": cbai_health,
            "embeddings_count": self.embeddings.session_count,
        }

    # =========================================================================
    # Suggestions (Phase 2)
    # =========================================================================

    async def suggest_response(
        self,
        question: str,
        context: str,
        session_slug: Optional[str] = None,
    ) -> Suggestion:
        """Generate a response suggestion for a waiting session."""
        return await self.suggestions.generate(
            question=question,
            context=context,
            session_slug=session_slug,
        )

    # =========================================================================
    # Summarization (Phase 3)
    # =========================================================================

    async def summarize_session(
        self,
        buffer: str,
        session_slug: Optional[str] = None,
    ) -> Summary:
        """Generate a summary of session activity."""
        return await self.summarizer.summarize(
            buffer=buffer,
            session_slug=session_slug,
        )

    # =========================================================================
    # Priority (Phase 4)
    # =========================================================================

    async def calculate_priority(
        self,
        question: str,
        context: str,
        wait_time_seconds: int,
        session_slug: Optional[str] = None,
    ) -> Priority:
        """Calculate priority for a waiting session."""
        return await self.priority.calculate(
            question=question,
            context=context,
            wait_time_seconds=wait_time_seconds,
            session_slug=session_slug,
        )

    # =========================================================================
    # Embeddings / Related Sessions (Phase 5)
    # =========================================================================

    async def update_session_embedding(
        self,
        slug: str,
        buffer: str,
        summary: Optional[str] = None,
        topics: Optional[list[str]] = None,
    ) -> None:
        """Update embedding for a session."""
        await self.embeddings.update(
            slug=slug,
            buffer=buffer,
            summary=summary,
            topics=topics,
        )

    def find_related_sessions(
        self,
        slug: str,
        threshold: float = None,
    ) -> list[RelatedSession]:
        """Find sessions related to the given session."""
        return self.embeddings.find_related(slug, threshold)

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for arbitrary text."""
        return await self.client.embed(text)

    # =========================================================================
    # Routing (Phase 6)
    # =========================================================================

    async def suggest_route(
        self,
        task_description: str,
        available_sessions: list[dict],
    ) -> dict:
        """
        Suggest which session should handle a task.

        Args:
            task_description: Description of the task
            available_sessions: List of session dicts with slug, state, summary

        Returns:
            Routing recommendation with session and reasoning
        """
        if not available_sessions:
            return {
                "recommended": None,
                "reason": "No sessions available",
                "alternatives": [],
                "suggest_new": True,
            }

        try:
            # Embed the task description
            task_embedding = await self.client.embed(task_description)

            if isinstance(task_embedding, list) and len(task_embedding) > 0:
                if isinstance(task_embedding[0], list):
                    task_embedding = task_embedding[0]

            # Find similar sessions
            matches = self.embeddings.find_similar_to_text(
                text=task_description,
                embedding=task_embedding,
                threshold=settings.routing_match_threshold,
            )

            if not matches:
                return {
                    "recommended": None,
                    "reason": "No sessions match this task",
                    "alternatives": [],
                    "suggest_new": True,
                }

            # Filter to available (non-error) sessions
            available_slugs = {
                s["slug"] for s in available_sessions
                if s.get("state") != "error"
            }

            valid_matches = [m for m in matches if m.slug in available_slugs]

            if not valid_matches:
                return {
                    "recommended": None,
                    "reason": "Matching sessions not available",
                    "alternatives": [],
                    "suggest_new": True,
                }

            best = valid_matches[0]

            # Build alternatives
            alternatives = []
            for match in valid_matches[1:4]:
                session = next(
                    (s for s in available_sessions if s["slug"] == match.slug),
                    None
                )
                if session:
                    alternatives.append(RoutingCandidate(
                        slug=match.slug,
                        match_score=match.similarity,
                        current_state=session.get("state", "unknown"),
                        summary=match.context_summary,
                        availability="waiting" if session.get("state") == "waiting" else "busy",
                    ))

            return {
                "recommended": best.slug,
                "reason": f"Best match ({best.similarity:.0%} similar): {best.context_summary[:50]}",
                "alternatives": alternatives,
                "suggest_new": best.similarity < 0.7,
            }

        except Exception as e:
            logger.error(f"Failed to suggest route: {e}")
            return {
                "recommended": None,
                "reason": f"Routing error: {e}",
                "alternatives": [],
                "suggest_new": True,
            }


# Global service instance
_service: Optional[IntelligenceService] = None


def get_intelligence_service() -> IntelligenceService:
    """Get or create the global intelligence service"""
    global _service
    if _service is None:
        _service = IntelligenceService()
    return _service
