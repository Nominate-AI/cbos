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


# =============================================================================
# SKILL MODELS - Multi-step workflow definitions
# =============================================================================


class StepType(str, Enum):
    """Types of steps in a skill workflow"""

    BASH = "bash"  # Execute shell command
    EDIT = "edit"  # Edit a file (pattern replacement)
    READ = "read"  # Read a file
    CONFIRM = "confirm"  # Ask user for confirmation
    BRANCH = "branch"  # Conditional branching


class ParameterType(str, Enum):
    """Types of skill parameters"""

    STRING = "string"
    SEMVER = "semver"  # Semantic version (1.2.3)
    PATH = "path"  # File or directory path
    CHOICE = "choice"  # One of predefined choices
    BOOL = "bool"


class SkillTrigger(BaseModel):
    """How to detect when a skill should be suggested"""

    pattern: str  # Regex pattern with {param} placeholders
    embedding: list[float] | None = None  # Pre-computed for similarity
    confidence: float = 0.8  # Min similarity threshold


class SkillParameter(BaseModel):
    """A parameter for a skill"""

    name: str
    type: ParameterType = ParameterType.STRING
    description: str = ""
    required: bool = True
    default: str | None = None
    choices: list[str] | None = None  # For type=choice


class SkillStep(BaseModel):
    """A single step in a skill workflow"""

    name: str
    type: StepType
    description: str = ""

    # For type=bash
    command: str | None = None
    expect_exit: int | None = None  # Expected exit code

    # For type=edit
    file: str | None = None  # Glob pattern supported
    pattern: str | None = None  # Regex to find
    replacement: str | None = None  # Replacement with {params}

    # For type=read
    # Uses 'file' field

    # For type=confirm
    message: str | None = None

    # For type=branch
    condition: str | None = None  # Shell command, branch on exit code
    then_steps: list[str] | None = None  # Step names if condition passes
    else_steps: list[str] | None = None  # Step names if condition fails


class SkillCondition(BaseModel):
    """Pre/post condition for a skill"""

    command: str  # Shell command to check
    expect: str | None = None  # Expected stdout (regex)
    expect_exit: int | None = None  # Expected exit code
    message: str  # Error message if condition fails


class Skill(BaseModel):
    """A reusable multi-step workflow"""

    id: int | None = None
    name: str  # Unique identifier (e.g., "release")
    version: str = "1.0.0"
    description: str

    # How to detect this skill should run
    triggers: list[SkillTrigger] = Field(default_factory=list)

    # Input parameters
    parameters: list[SkillParameter] = Field(default_factory=list)

    # Execution flow
    preconditions: list[SkillCondition] = Field(default_factory=list)
    steps: list[SkillStep] = Field(default_factory=list)
    postconditions: list[SkillCondition] = Field(default_factory=list)

    # Scope
    project_scope: str | None = None  # None = global, else project-specific
    author: str | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Source tracking (if mined from logs)
    source_sessions: list[str] = Field(default_factory=list)
    confidence: float = 1.0  # 1.0 = authored, <1.0 = mined


class SkillMatch(BaseModel):
    """Result from skill detection"""

    skill: Skill
    trigger: SkillTrigger
    similarity: float = Field(ge=0.0, le=1.0)
    extracted_params: dict[str, str] = Field(default_factory=dict)


class SkillCandidate(BaseModel):
    """A potential skill mined from conversation logs"""

    skill_type: str  # Detected category (release, deploy, etc.)
    session_file: str
    tool_sequence: list[tuple[str, str]] = Field(
        default_factory=list
    )  # (tool_name, pattern)
    user_input: str = ""  # Original user request
    confidence: float = 0.0
    suggested_name: str = ""
    suggested_triggers: list[str] = Field(default_factory=list)
