"""CBOS Intelligence Layer - AI-powered session management"""

from .client import CBAIClient
from .config import IntelligenceSettings
from .models import (
    Suggestion,
    Summary,
    Priority,
    QuestionType,
    RelatedSession,
    RoutingCandidate,
    SuggestionResponse,
    SummaryResponse,
    PrioritizedSession,
    RouteResponse,
)
from .suggestions import SuggestionGenerator
from .summarizer import SessionSummarizer
from .priority import PriorityCalculator
from .embeddings import SessionEmbeddingStore
from .service import IntelligenceService, get_intelligence_service

__all__ = [
    "CBAIClient",
    "IntelligenceSettings",
    "IntelligenceService",
    "get_intelligence_service",
    "Suggestion",
    "Summary",
    "Priority",
    "QuestionType",
    "RelatedSession",
    "RoutingCandidate",
    "SuggestionResponse",
    "SummaryResponse",
    "PrioritizedSession",
    "RouteResponse",
    "SuggestionGenerator",
    "SessionSummarizer",
    "PriorityCalculator",
    "SessionEmbeddingStore",
]
