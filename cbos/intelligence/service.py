"""Main intelligence service - coordinates all AI features"""

import logging
from typing import Optional

from .client import CBAIClient
from .config import settings
from .models import Suggestion, Summary, Priority, QuestionType
from .suggestions import SuggestionGenerator

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
        self.suggestions = SuggestionGenerator(self.client)

        # Caches (to be expanded)
        self._summary_cache: dict[str, tuple[Summary, float]] = {}

    async def health_check(self) -> dict:
        """Check health of intelligence service and CBAI"""
        cbai_health = await self.client.health()
        return {
            "intelligence": "ok",
            "cbai": cbai_health,
        }

    # =========================================================================
    # Suggestions
    # =========================================================================

    async def suggest_response(
        self,
        question: str,
        context: str,
        session_slug: Optional[str] = None,
    ) -> Suggestion:
        """
        Generate a response suggestion for a waiting session.

        Args:
            question: The question Claude is asking
            context: Recent buffer content
            session_slug: Session identifier

        Returns:
            Suggestion with response and confidence
        """
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
        """
        Generate a summary of session activity.

        Args:
            buffer: Session buffer content
            session_slug: Session identifier

        Returns:
            Summary with short/detailed descriptions and topics
        """
        import hashlib
        buffer_hash = hashlib.md5(buffer.encode()).hexdigest()[:8]

        # Check cache
        if session_slug and session_slug in self._summary_cache:
            cached, timestamp = self._summary_cache[session_slug]
            if cached.buffer_hash == buffer_hash:
                return cached

        # Generate summary using CBAI
        try:
            short_summary = await self.client.summarize(
                buffer[-3000:],  # Last 3000 chars
                max_length=20,
                style="concise",
            )

            detailed_summary = await self.client.summarize(
                buffer[-3000:],
                max_length=100,
                style="detailed",
            )

            topics = await self.client.topics(buffer[-3000:])

            # Extract last action from buffer
            lines = buffer.strip().split("\n")
            last_action = lines[-1][:100] if lines else ""

            summary = Summary(
                short=short_summary or "Working...",
                detailed=detailed_summary or short_summary or "Session active",
                topics=topics[:5],
                last_action=last_action,
                buffer_hash=buffer_hash,
            )

            # Cache it
            if session_slug:
                import time
                self._summary_cache[session_slug] = (summary, time.time())

            return summary

        except Exception as e:
            logger.error(f"Failed to summarize session: {e}")
            return Summary(
                short="Unable to summarize",
                detailed=str(e),
                topics=[],
                last_action="",
                buffer_hash=buffer_hash,
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
        """
        Calculate priority score for a waiting session.

        Args:
            question: The question being asked
            context: Recent buffer content
            wait_time_seconds: How long session has been waiting
            session_slug: Session identifier

        Returns:
            Priority with score and reasoning
        """
        # First, classify the question type
        suggestion = await self.suggest_response(question, context, session_slug)
        question_type = suggestion.question_type

        # Base score from question type
        type_scores = {
            QuestionType.ERROR: 0.9,
            QuestionType.DECISION: 0.7,
            QuestionType.PERMISSION: 0.5,
            QuestionType.CLARIFICATION: 0.6,
            QuestionType.CONFIRMATION: 0.4,
            QuestionType.INFORMATION: 0.3,
            QuestionType.UNKNOWN: 0.5,
        }
        base_score = type_scores.get(question_type, 0.5)

        # Adjust for wait time (max +0.3 for waiting > 5 minutes)
        wait_factor = min(wait_time_seconds / 300, 1.0) * 0.3
        score = min(base_score + wait_factor, 1.0)

        # Generate reason
        reasons = []
        if question_type == QuestionType.ERROR:
            reasons.append("Error requires attention")
        if question_type == QuestionType.DECISION:
            reasons.append("Decision needed to proceed")
        if wait_time_seconds > 120:
            reasons.append(f"Waiting {wait_time_seconds // 60}+ minutes")

        return Priority(
            score=score,
            reason="; ".join(reasons) or "Standard priority",
            question_type=question_type,
            wait_time_seconds=wait_time_seconds,
            suggested_action=suggestion.response if suggestion.confidence > 0.6 else "Review and respond",
        )

    # =========================================================================
    # Embeddings / Related Sessions (Phase 5)
    # =========================================================================

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for text"""
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
            available_sessions: List of session dicts with slug, summary

        Returns:
            Routing recommendation
        """
        # TODO: Implement in Phase 6
        return {
            "recommended": None,
            "reason": "Routing not yet implemented",
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
