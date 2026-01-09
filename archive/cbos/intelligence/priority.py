"""Priority calculation for waiting sessions"""

import logging
from typing import Optional

from .client import CBAIClient
from .config import settings
from .models import Priority, QuestionType

logger = logging.getLogger(__name__)


CLASSIFY_SYSTEM_PROMPT = """Classify this question from Claude Code.

Question types:
- permission: Asking to proceed, run command, make change ("Should I?", "Can I?", "Proceed?")
- decision: Needs choice between options ("Which?", "Option A or B?")
- clarification: Needs more information ("What do you mean?", "Where should?")
- error: Error occurred, needs guidance ("Failed to", "Error:", "Exception")
- confirmation: Checking if something is correct ("Is this right?", "Does this look ok?")
- information: Asking for facts or details ("What is?", "How does?")

Respond with valid JSON only:
{
  "question_type": "permission|decision|clarification|error|confirmation|information|unknown",
  "urgency": 0.0-1.0,
  "reasoning": "brief explanation"
}"""


# Base priority scores by question type
TYPE_PRIORITIES = {
    QuestionType.ERROR: 0.9,
    QuestionType.DECISION: 0.7,
    QuestionType.CLARIFICATION: 0.6,
    QuestionType.PERMISSION: 0.5,
    QuestionType.CONFIRMATION: 0.4,
    QuestionType.INFORMATION: 0.3,
    QuestionType.UNKNOWN: 0.5,
}


class PriorityCalculator:
    """Calculate priority scores for waiting sessions"""

    def __init__(self, client: Optional[CBAIClient] = None):
        self.client = client or CBAIClient()

    async def calculate(
        self,
        question: str,
        context: str,
        wait_time_seconds: int,
        session_slug: Optional[str] = None,
    ) -> Priority:
        """
        Calculate priority for a waiting session.

        Args:
            question: The question being asked
            context: Recent buffer content
            wait_time_seconds: How long session has been waiting
            session_slug: Session identifier

        Returns:
            Priority with score, reason, and suggested action
        """
        # Classify the question
        question_type, ai_urgency = await self._classify_question(question, context)

        # Calculate base score from question type
        base_score = TYPE_PRIORITIES.get(question_type, 0.5)

        # Factor in AI-assessed urgency (weight: 0.2)
        if ai_urgency is not None:
            base_score = base_score * 0.8 + ai_urgency * 0.2

        # Add wait time factor (max +0.2 for waiting > 5 minutes)
        wait_factor = min(wait_time_seconds / 300, 1.0) * 0.2
        score = min(base_score + wait_factor, 1.0)

        # Generate reason
        reasons = []
        if question_type == QuestionType.ERROR:
            reasons.append("Error needs attention")
        elif question_type == QuestionType.DECISION:
            reasons.append("Decision required")
        elif question_type == QuestionType.CLARIFICATION:
            reasons.append("Needs clarification")

        if wait_time_seconds > 300:
            reasons.append(f"Waiting {wait_time_seconds // 60}+ min")
        elif wait_time_seconds > 60:
            reasons.append(f"Waiting {wait_time_seconds}s")

        # Suggest action
        suggested_action = self._suggest_action(question_type, question)

        return Priority(
            score=round(score, 2),
            reason="; ".join(reasons) if reasons else "Standard priority",
            question_type=question_type,
            wait_time_seconds=wait_time_seconds,
            suggested_action=suggested_action,
        )

    async def _classify_question(
        self,
        question: str,
        context: str,
    ) -> tuple[QuestionType, Optional[float]]:
        """Classify question type using AI"""
        # First try pattern matching for speed
        question_type = self._pattern_classify(question)
        if question_type != QuestionType.UNKNOWN:
            return question_type, None

        # Fall back to AI classification
        try:
            truncated_context = context[-1000:] if len(context) > 1000 else context

            result = await self.client.chat_json(
                messages=[
                    {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Context:\n{truncated_context}\n\nQuestion: {question}"},
                ],
                provider=settings.priority_model,
                model=settings.priority_model,
                temperature=0.2,
            )

            if "error" in result:
                return QuestionType.UNKNOWN, None

            type_str = result.get("question_type", "unknown")
            urgency = result.get("urgency")

            try:
                question_type = QuestionType(type_str.lower())
            except ValueError:
                question_type = QuestionType.UNKNOWN

            return question_type, urgency

        except Exception as e:
            logger.error(f"Failed to classify question: {e}")
            return QuestionType.UNKNOWN, None

    def _pattern_classify(self, question: str) -> QuestionType:
        """Fast pattern-based classification"""
        q = question.lower()

        # Error patterns
        if any(word in q for word in ["error", "failed", "exception", "couldn't", "unable to"]):
            return QuestionType.ERROR

        # Permission patterns
        if any(word in q for word in ["should i", "shall i", "can i", "may i", "proceed", "continue"]):
            return QuestionType.PERMISSION

        # Decision patterns
        if any(word in q for word in ["which", "option", "choose", " or "]):
            return QuestionType.DECISION

        # Confirmation patterns
        if any(word in q for word in ["is this", "does this", "look right", "correct", "okay"]):
            return QuestionType.CONFIRMATION

        # Clarification patterns
        if any(word in q for word in ["what do you mean", "clarify", "specify", "which file", "what should"]):
            return QuestionType.CLARIFICATION

        return QuestionType.UNKNOWN

    def _suggest_action(self, question_type: QuestionType, question: str) -> str:
        """Suggest default action based on question type"""
        suggestions = {
            QuestionType.PERMISSION: "Likely safe to approve with 'yes'",
            QuestionType.DECISION: "Review options and decide",
            QuestionType.CLARIFICATION: "Provide specific guidance",
            QuestionType.ERROR: "Investigate error and advise",
            QuestionType.CONFIRMATION: "Review and confirm or correct",
            QuestionType.INFORMATION: "Provide requested information",
            QuestionType.UNKNOWN: "Review and respond",
        }
        return suggestions.get(question_type, "Review and respond")

    async def prioritize_sessions(
        self,
        sessions: list[dict],
    ) -> list[tuple[dict, Priority]]:
        """
        Calculate priorities for multiple sessions and sort.

        Args:
            sessions: List of session dicts with question, context, wait_time

        Returns:
            List of (session, priority) tuples sorted by score descending
        """
        results = []
        for session in sessions:
            priority = await self.calculate(
                question=session.get("question", ""),
                context=session.get("context", ""),
                wait_time_seconds=session.get("wait_time", 0),
                session_slug=session.get("slug"),
            )
            results.append((session, priority))

        # Sort by priority score descending
        results.sort(key=lambda x: x[1].score, reverse=True)
        return results
