"""AI-powered response suggestion generator"""

import logging
from typing import Optional

from .client import CBAIClient
from .config import settings
from .models import Suggestion, QuestionType

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an assistant helping a developer respond to Claude Code.

Claude Code is an AI coding assistant running in a terminal. It asks questions when it needs:
- Permission to run commands or make changes
- Decisions between multiple approaches
- Clarification about requirements
- Confirmation that something looks correct

Based on the conversation context and question, suggest a helpful response.

Guidelines:
1. Be concise - most responses are short (1-10 words)
2. For permission questions: usually "yes", "y", or "go ahead"
3. For decisions: pick the most sensible option or ask for more context
4. For clarification: provide specific, actionable guidance
5. For errors: suggest how to proceed or what to investigate
6. If genuinely unsure, say so and offer options

Respond with valid JSON only:
{
  "response": "your suggested response",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation of why this response",
  "question_type": "permission|decision|clarification|error|information|confirmation|unknown",
  "alternatives": ["optional", "alternative", "responses"]
}"""


class SuggestionGenerator:
    """Generate response suggestions using CBAI"""

    def __init__(self, client: Optional[CBAIClient] = None):
        self.client = client or CBAIClient()

    async def generate(
        self,
        question: str,
        context: str,
        session_slug: Optional[str] = None,
    ) -> Suggestion:
        """
        Generate a response suggestion for a waiting Claude session.

        Args:
            question: The question Claude is asking
            context: Recent buffer content for context
            session_slug: Session identifier (for logging)

        Returns:
            Suggestion with response, confidence, and reasoning
        """
        # Truncate context to last ~2000 chars to stay within token limits
        if len(context) > 2000:
            context = "..." + context[-2000:]

        user_message = f"""Session: {session_slug or 'unknown'}

Recent context:
{context}

Question being asked:
{question}

Suggest a response:"""

        try:
            result = await self.client.chat_json(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                provider=settings.suggestion_provider,
                model=settings.suggestion_model,
                temperature=0.3,
            )

            # Parse response
            if "error" in result:
                logger.warning(f"Suggestion generation returned error: {result}")
                return self._fallback_suggestion(question)

            return Suggestion(
                response=result.get("response", ""),
                confidence=float(result.get("confidence", 0.5)),
                reasoning=result.get("reasoning", ""),
                question_type=self._parse_question_type(result.get("question_type")),
                alternatives=result.get("alternatives", []),
            )

        except Exception as e:
            logger.error(f"Failed to generate suggestion: {e}")
            return self._fallback_suggestion(question)

    def _parse_question_type(self, type_str: Optional[str]) -> QuestionType:
        """Parse question type string to enum"""
        if not type_str:
            return QuestionType.UNKNOWN

        try:
            return QuestionType(type_str.lower())
        except ValueError:
            return QuestionType.UNKNOWN

    def _fallback_suggestion(self, question: str) -> Suggestion:
        """Generate a basic fallback suggestion when AI fails"""
        question_lower = question.lower()

        # Simple pattern matching for common cases
        if any(word in question_lower for word in ["proceed", "continue", "run", "execute", "should i"]):
            return Suggestion(
                response="yes",
                confidence=0.6,
                reasoning="Appears to be a permission request",
                question_type=QuestionType.PERMISSION,
                alternatives=["no", "let me check first"],
            )

        if "?" in question and ("or" in question_lower or "which" in question_lower):
            return Suggestion(
                response="",
                confidence=0.3,
                reasoning="Decision required - needs human input",
                question_type=QuestionType.DECISION,
                alternatives=[],
            )

        if any(word in question_lower for word in ["error", "failed", "couldn't", "unable"]):
            return Suggestion(
                response="Let's investigate the error",
                confidence=0.4,
                reasoning="Error detected - suggesting investigation",
                question_type=QuestionType.ERROR,
                alternatives=["skip this for now", "try a different approach"],
            )

        return Suggestion(
            response="",
            confidence=0.2,
            reasoning="Unable to determine appropriate response",
            question_type=QuestionType.UNKNOWN,
            alternatives=[],
        )

    async def generate_batch(
        self,
        sessions: list[dict],
    ) -> dict[str, Suggestion]:
        """
        Generate suggestions for multiple sessions.

        Args:
            sessions: List of session dicts with 'slug', 'question', 'buffer'

        Returns:
            Dict mapping slug to Suggestion
        """
        results = {}
        for session in sessions:
            slug = session.get("slug", "")
            question = session.get("question") or session.get("last_question", "")
            buffer = session.get("buffer") or session.get("buffer_tail", "")

            if question:
                results[slug] = await self.generate(
                    question=question,
                    context=buffer,
                    session_slug=slug,
                )

        return results
