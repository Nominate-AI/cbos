"""Pydantic models for intelligence features"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    """Types of questions Claude might ask"""
    PERMISSION = "permission"       # "Should I proceed?", "Run this command?"
    DECISION = "decision"           # "Which approach?", "Option A or B?"
    CLARIFICATION = "clarification" # "What do you mean by...?"
    ERROR = "error"                 # "Failed to...", "Error occurred"
    INFORMATION = "information"     # "What is the...?", "Where should...?"
    CONFIRMATION = "confirmation"   # "Is this correct?", "Does this look right?"
    UNKNOWN = "unknown"


class Suggestion(BaseModel):
    """AI-generated response suggestion"""
    response: str = Field(description="Suggested response text")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    reasoning: str = Field(description="Why this response was suggested")
    question_type: QuestionType = Field(default=QuestionType.UNKNOWN)
    alternatives: list[str] = Field(default_factory=list, description="Alternative responses")


class Summary(BaseModel):
    """Session activity summary"""
    short: str = Field(description="1-line summary for list view")
    detailed: str = Field(description="2-3 sentence description")
    topics: list[str] = Field(default_factory=list, description="Key themes")
    last_action: str = Field(description="Most recent action")
    buffer_hash: str = Field(description="Hash for cache invalidation")


class Priority(BaseModel):
    """Session priority assessment"""
    score: float = Field(ge=0.0, le=1.0, description="Priority score")
    reason: str = Field(description="Why this priority was assigned")
    question_type: QuestionType
    wait_time_seconds: int = Field(description="How long session has been waiting")
    suggested_action: str = Field(description="Recommended action")


class RelatedSession(BaseModel):
    """A session related to another by context"""
    slug: str
    similarity: float = Field(ge=0.0, le=1.0)
    context_summary: str
    shared_topics: list[str] = Field(default_factory=list)


class RoutingCandidate(BaseModel):
    """A session that could handle a task"""
    slug: str
    match_score: float = Field(ge=0.0, le=1.0)
    current_state: str
    summary: str
    availability: str = Field(description="idle, busy, or waiting")


# API Response models

class SuggestionResponse(BaseModel):
    """Response for /sessions/{slug}/suggest"""
    slug: str
    question: str
    suggestion: Suggestion


class SummaryResponse(BaseModel):
    """Response for /sessions/{slug}/summary"""
    slug: str
    summary: Summary


class PrioritizedSession(BaseModel):
    """Session with priority info"""
    slug: str
    state: str
    question: Optional[str]
    priority: Priority


class RouteResponse(BaseModel):
    """Response for /sessions/route"""
    recommended_session: Optional[str]
    recommendation_reason: str
    alternatives: list[RoutingCandidate]
    suggest_new: bool = Field(description="Whether to create a new session")
