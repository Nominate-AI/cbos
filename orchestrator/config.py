"""Configuration for the CBOS Orchestrator"""

from pathlib import Path

from pydantic_settings import BaseSettings


class OrchestratorSettings(BaseSettings):
    """Settings for the CBOS Orchestrator"""

    # Database
    pattern_db_path: Path = Path.home() / ".cbos" / "patterns.db"

    # CBAI service
    cbai_url: str = "https://ai.nominate.ai"

    # Embedding
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # Vector store (vectl)
    vector_store_path: Path = Path.home() / ".cbos" / "vectors.bin"
    vector_dim: int = 768  # Must match embedding_dim
    num_clusters: int = 50  # K-means clusters for similarity search
    vector_log_path: Path = Path.home() / ".cbos" / "vectors.log"

    # Extraction
    context_chars: int = 500  # Characters of context before question

    # Query defaults
    similarity_threshold: float = 0.7
    max_query_results: int = 10

    # Request settings
    request_timeout: float = 30.0
    batch_size: int = 50

    # WebSocket Listener
    listener_port: int = 32205
    auto_answer_threshold: float = 0.95  # Confidence for auto-answering
    suggestion_threshold: float = 0.80  # Confidence for suggestions
    auto_answer_enabled: bool = False  # Disabled by default for safety

    model_config = {"env_prefix": "CBOS_ORCHESTRATOR_"}


settings = OrchestratorSettings()
