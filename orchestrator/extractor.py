"""Extract decision patterns from Claude Code conversation logs"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from .config import settings
from .models import DecisionPattern, ExtractedQuestion, QuestionOption, QuestionType

logger = logging.getLogger(__name__)


class DecisionPatternExtractor:
    """
    Extract AskUserQuestion -> response patterns from Claude conversation logs.

    Parses JSONL files from ~/.claude/projects/ and extracts patterns where
    Claude asked questions and the user responded.
    """

    CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

    def __init__(
        self,
        project_filter: Optional[str] = None,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
        include_thinking: bool = True,
        context_chars: int = None,
    ):
        self.project_filter = project_filter
        self.after_date = after_date
        self.before_date = before_date
        self.include_thinking = include_thinking
        self.context_chars = context_chars or settings.context_chars

    def get_project_dirs(self) -> Iterator[Path]:
        """Yield project directories, optionally filtered"""
        if not self.CLAUDE_PROJECTS_DIR.exists():
            logger.warning(f"Projects directory not found: {self.CLAUDE_PROJECTS_DIR}")
            return

        for project_dir in self.CLAUDE_PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue

            # Apply project filter if specified
            if self.project_filter:
                if self.project_filter.lower() not in project_dir.name.lower():
                    continue

            yield project_dir

    def get_session_files(self, project_dir: Path) -> Iterator[Path]:
        """Yield JSONL session files from a project directory"""
        for jsonl_file in project_dir.glob("*.jsonl"):
            # Skip agent files (subagent logs)
            if jsonl_file.name.startswith("agent-"):
                continue
            yield jsonl_file

    def parse_timestamp(self, ts: str) -> Optional[datetime]:
        """Parse ISO timestamp string"""
        try:
            ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None

    def is_in_date_range(self, timestamp: str) -> bool:
        """Check if timestamp falls within configured date range"""
        dt = self.parse_timestamp(timestamp)
        if not dt:
            return True

        if self.after_date and dt < self.after_date:
            return False
        if self.before_date and dt > self.before_date:
            return False
        return True

    def extract_patterns(self) -> Iterator[DecisionPattern]:
        """
        Extract all AskUserQuestion patterns from conversation logs.

        Algorithm:
        1. Iterate through all project directories
        2. For each JSONL session file:
           a. Load all messages
           b. Find assistant messages with AskUserQuestion tool_use
           c. Find the user's answer (from answers field or next user message)
           d. Extract context from messages before the question
           e. Yield DecisionPattern
        """
        for project_dir in self.get_project_dirs():
            project_path = self._normalize_project_path(project_dir.name)

            for session_file in self.get_session_files(project_dir):
                try:
                    yield from self._extract_from_session(session_file, project_path)
                except Exception as e:
                    logger.error(f"Error processing {session_file}: {e}")

    def _extract_from_session(
        self, session_file: Path, project_path: str
    ) -> Iterator[DecisionPattern]:
        """Extract patterns from a single session file"""
        messages = []

        # Load all messages from file
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    messages.append(data)
                except json.JSONDecodeError:
                    continue

        # Process messages looking for AskUserQuestion tool uses
        for i, msg in enumerate(messages):
            if msg.get("type") != "assistant":
                continue

            message_data = msg.get("message", {})
            content = message_data.get("content", [])

            if not isinstance(content, list):
                continue

            # Find AskUserQuestion tool uses
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                if block.get("name") != "AskUserQuestion":
                    continue

                tool_use_id = block.get("id", "")
                tool_input = block.get("input", {})

                # Check date range
                timestamp = msg.get("timestamp", "")
                if not self.is_in_date_range(timestamp):
                    continue

                # Parse the question(s)
                questions = self._parse_questions(tool_input)
                if not questions:
                    continue

                # Get the answer
                answer = self._find_answer(tool_input, messages, i, tool_use_id)
                if not answer:
                    continue

                # Extract context
                context = self._extract_context(messages, i)

                # Extract thinking if available
                thinking = None
                if self.include_thinking:
                    thinking = self._extract_thinking(content)

                # Classify question type
                question_type = self._classify_question_type(questions[0])

                # Build pattern
                pattern = DecisionPattern(
                    project=project_path,
                    session_id=msg.get("sessionId", ""),
                    tool_use_id=tool_use_id,
                    question_text=self._combine_questions(questions),
                    question_header=questions[0].header if questions else "",
                    question_type=question_type,
                    options=[
                        opt for q in questions for opt in q.options
                    ],
                    context_before=context,
                    thinking=thinking,
                    user_answer=answer,
                    is_selected_option=self._is_selected_option(answer, questions),
                    timestamp=self.parse_timestamp(timestamp) or datetime.now(),
                )

                yield pattern

    def _parse_questions(self, tool_input: dict) -> list[ExtractedQuestion]:
        """Parse AskUserQuestion input into ExtractedQuestion objects"""
        questions = []

        # Handle the questions array format
        raw_questions = tool_input.get("questions", [])

        for q in raw_questions:
            options = []
            for opt in q.get("options", []):
                options.append(QuestionOption(
                    label=opt.get("label", ""),
                    description=opt.get("description", ""),
                ))

            questions.append(ExtractedQuestion(
                question=q.get("question", ""),
                header=q.get("header", ""),
                options=options,
                multi_select=q.get("multiSelect", False),
            ))

        return questions

    def _find_answer(
        self,
        tool_input: dict,
        messages: list[dict],
        current_idx: int,
        tool_use_id: str,
    ) -> Optional[str]:
        """Find the user's answer to the question"""
        # First check if answers are in the tool input itself
        answers = tool_input.get("answers", {})
        if answers:
            # Combine all answers
            answer_parts = []
            for key, value in answers.items():
                if isinstance(value, list):
                    answer_parts.extend(value)
                else:
                    answer_parts.append(str(value))
            if answer_parts:
                return " | ".join(answer_parts)

        # Look for tool_result in subsequent messages
        for msg in messages[current_idx + 1:]:
            msg_type = msg.get("type")

            # Check for user message with tool_result
            if msg_type == "user":
                message_data = msg.get("message", {})
                content = message_data.get("content", [])

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            if block.get("tool_use_id") == tool_use_id:
                                result_content = block.get("content", "")
                                if result_content:
                                    return result_content

                # If we hit a regular user message, use that as the answer
                if isinstance(content, str) and content.strip():
                    return content.strip()

            # Stop if we hit another assistant message
            if msg_type == "assistant":
                break

        return None

    def _extract_context(self, messages: list[dict], before_idx: int) -> str:
        """Extract conversation context before the question"""
        context_parts = []
        chars_collected = 0

        for i in range(before_idx - 1, -1, -1):
            if chars_collected >= self.context_chars:
                break

            msg = messages[i]
            msg_type = msg.get("type")

            if msg_type not in ("user", "assistant"):
                continue

            message_data = msg.get("message", {})
            content = message_data.get("content", "")

            # Extract text content
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                text = " ".join(text_parts)

            if text:
                role = "User" if msg_type == "user" else "Assistant"
                context_parts.insert(0, f"[{role}]: {text[:500]}")
                chars_collected += len(text[:500])

        return "\n".join(context_parts)[-self.context_chars:]

    def _extract_thinking(self, content: list) -> Optional[str]:
        """Extract thinking block from content"""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                return block.get("thinking", "")
        return None

    def _classify_question_type(self, question: ExtractedQuestion) -> QuestionType:
        """Classify question type using heuristics"""
        q_lower = question.question.lower()

        # Permission patterns
        permission_patterns = [
            r"\bshould i (proceed|continue|run|execute|do)\b",
            r"\bcan i (proceed|continue|run|execute)\b",
            r"\bproceed\?",
            r"\brun (this|the|these)\b",
        ]
        for pattern in permission_patterns:
            if re.search(pattern, q_lower):
                return QuestionType.PERMISSION

        # Decision patterns (has options)
        if question.options and len(question.options) >= 2:
            return QuestionType.DECISION

        # Confirmation patterns
        confirmation_patterns = [
            r"\b(correct|right|ok|okay|look good|looks good)\?",
            r"\bis (this|that) (correct|right|what you)\b",
        ]
        for pattern in confirmation_patterns:
            if re.search(pattern, q_lower):
                return QuestionType.CONFIRMATION

        # Clarification patterns
        clarification_patterns = [
            r"\bwhat (do you mean|exactly|specifically)\b",
            r"\bcan you (clarify|explain|elaborate)\b",
            r"\bwhich (one|version|option)\b",
        ]
        for pattern in clarification_patterns:
            if re.search(pattern, q_lower):
                return QuestionType.CLARIFICATION

        # Information patterns
        information_patterns = [
            r"\bwhat is (the|your)\b",
            r"\bwhere (is|are|should)\b",
            r"\bhow (do|should|would)\b",
        ]
        for pattern in information_patterns:
            if re.search(pattern, q_lower):
                return QuestionType.INFORMATION

        # Error patterns
        if "error" in q_lower or "fail" in q_lower:
            return QuestionType.ERROR

        return QuestionType.UNKNOWN

    def _combine_questions(self, questions: list[ExtractedQuestion]) -> str:
        """Combine multiple questions into a single text"""
        parts = []
        for q in questions:
            text = q.question
            if q.header:
                text = f"[{q.header}] {text}"
            parts.append(text)
        return " | ".join(parts)

    def _is_selected_option(
        self, answer: str, questions: list[ExtractedQuestion]
    ) -> bool:
        """Check if answer matches one of the options"""
        answer_lower = answer.lower().strip()
        for q in questions:
            for opt in q.options:
                if opt.label.lower() in answer_lower:
                    return True
        return False

    def _normalize_project_path(self, dir_name: str) -> str:
        """Convert directory name back to readable project path"""
        # Directory names are like: -home-user-projects-foo
        return dir_name.replace("-", "/").lstrip("/")
