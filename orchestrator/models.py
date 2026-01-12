"""Pydantic data models for the CBOS Orchestrator"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from pydantic import Field


class QuestionType(str, Enum):
    """Types of questions Claude asks via AskUserQuestion"""

    PERMISSION = "permission"  # "Should I proceed?", "Run this?"
    DECISION = "decision"  # "Which approach?", "Option A or B?"
    CLARIFICATION = "clarification"  # "What do you mean by...?"
    INFORMATION = "information"  # "What is the X?", "Where is Y?"
    CONFIRMATION = "confirmation"  # "Is this correct?", "Look right?"
    ERROR = "error"  # Error-related questions
    UNKNOWN = "unknown"


class QuestionOption(BaseModel):
    """An option presented in an AskUserQuestion"""

    label: str
    description: str = ""


class ExtractedQuestion(BaseModel):
    """A single question from AskUserQuestion input"""

    question: str
    header: str = ""
    options: list[QuestionOption] = Field(default_factory=list)
    multi_select: bool = False


class DecisionPattern(BaseModel):
    """A pattern extracted from AskUserQuestion -> response pair"""

    id: int | None = None

    # Source
    project: str
    session_id: str
    tool_use_id: str

    # Question
    question_text: str  # Concatenated question text
    question_header: str = ""  # First header
    question_type: QuestionType = QuestionType.UNKNOWN
    options: list[QuestionOption] = Field(default_factory=list)

    # Context
    context_before: str = ""  # Text before the question
    thinking: str | None = None  # Claude's thinking

    # Response
    user_answer: str
    is_selected_option: bool = False  # True if answer was from options

    # Vector (not stored in model, loaded separately)
    embedding: list[float] | None = Field(default=None, exclude=True)

    # Timestamps
    timestamp: datetime
    extracted_at: datetime = Field(default_factory=datetime.now)


class PatternMatch(BaseModel):
    """Result from similarity search"""

    pattern: DecisionPattern
    similarity: float = Field(ge=0.0, le=1.0)


class PatternStats(BaseModel):
    """Statistics about the pattern database"""

    total_patterns: int = 0
    patterns_with_embeddings: int = 0
    question_types: dict[str, int] = Field(default_factory=dict)
    projects: dict[str, int] = Field(default_factory=dict)
    date_range: tuple[str | None, str | None] = (None, None)
