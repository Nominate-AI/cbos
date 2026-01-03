"""Intelligence layer configuration"""

from pydantic_settings import BaseSettings


class IntelligenceSettings(BaseSettings):
    """Configuration for AI-powered features"""

    # CBAI service
    cbai_url: str = "https://ai.nominate.ai"

    # Model selection - use fast local models by default
    suggestion_model: str = "mistral-small3.2:latest"
    suggestion_provider: str = "ollama"

    summary_model: str = "mistral-small3.2:latest"
    summary_provider: str = "ollama"

    priority_model: str = "mistral-small3.2:latest"
    priority_provider: str = "ollama"

    # Use Claude for complex reasoning when needed
    complex_model: str = "claude-sonnet-4-5-20250929"
    complex_provider: str = "claude"

    # Embedding model
    embedding_model: str = "nomic-embed-text"

    # Caching
    summary_cache_ttl: int = 30  # seconds
    embedding_update_interval: int = 60  # seconds

    # Thresholds
    suggestion_confidence_threshold: float = 0.7
    related_session_threshold: float = 0.7
    routing_match_threshold: float = 0.6

    # Timeouts
    request_timeout: float = 30.0

    class Config:
        env_prefix = "CBOS_AI_"


# Global settings instance
settings = IntelligenceSettings()
