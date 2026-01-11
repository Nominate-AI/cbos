"""High-performance vector storage using vectl (Vector Cluster Store)"""

import logging
from pathlib import Path
from typing import Optional

from vector_store import create_store
from vector_cluster_store_py import VectorClusterStore, Logger as VectlLogger

from .config import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """
    High-performance vector storage using vectl.

    Uses K-means clustering for efficient similarity search.
    File-backed storage that persists across restarts.
    """

    def __init__(
        self,
        store_path: Optional[Path] = None,
        vector_dim: int = None,
        num_clusters: int = None,
        log_path: Optional[Path] = None,
    ):
        self.store_path = store_path or settings.vector_store_path
        self.vector_dim = vector_dim or settings.vector_dim
        self.num_clusters = num_clusters or settings.num_clusters
        self.log_path = log_path or settings.vector_log_path
        self._store: Optional[VectorClusterStore] = None
        self._vector_count: int = 0

    def connect(self) -> None:
        """Initialize or open existing vector store"""
        # Ensure directory exists
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._store = create_store(
                str(self.store_path),
                vector_dim=self.vector_dim,
                num_clusters=self.num_clusters,
                log_file=str(self.log_path),
            )
            logger.info(
                f"Connected to vector store: {self.store_path} "
                f"(dim={self.vector_dim}, clusters={self.num_clusters})"
            )
        except Exception as e:
            logger.error(f"Failed to connect to vector store: {e}")
            raise

    def close(self) -> None:
        """Close the store"""
        self._store = None
        logger.info("Vector store closed")

    @property
    def is_connected(self) -> bool:
        """Check if store is connected"""
        return self._store is not None

    def add_vector(
        self, vector_id: int, embedding: list[float], metadata: str = ""
    ) -> None:
        """
        Store embedding for a pattern.

        Args:
            vector_id: Pattern ID (must match SQLite pattern.id)
            embedding: 768-dimensional embedding vector
            metadata: Optional metadata string (e.g., question text)
        """
        if not self._store:
            raise RuntimeError("Vector store not connected")

        if len(embedding) != self.vector_dim:
            raise ValueError(
                f"Embedding dimension mismatch: got {len(embedding)}, "
                f"expected {self.vector_dim}"
            )

        self._store.store_vector(vector_id, embedding, metadata)
        self._vector_count += 1

    def find_similar(
        self, query_embedding: list[float], k: int = 10
    ) -> list[tuple[int, float]]:
        """
        Find k most similar vectors using K-means clustering.

        Args:
            query_embedding: Query vector (768-dim)
            k: Number of results to return

        Returns:
            List of (vector_id, similarity_score) tuples, sorted by similarity desc
        """
        if not self._store:
            raise RuntimeError("Vector store not connected")

        if len(query_embedding) != self.vector_dim:
            raise ValueError(
                f"Query dimension mismatch: got {len(query_embedding)}, "
                f"expected {self.vector_dim}"
            )

        return self._store.find_similar_vectors(query_embedding, k)

    def get_vector(self, vector_id: int) -> Optional[list[float]]:
        """
        Retrieve embedding by vector ID.

        Args:
            vector_id: Pattern ID

        Returns:
            Embedding vector or None if not found
        """
        if not self._store:
            raise RuntimeError("Vector store not connected")

        try:
            return self._store.retrieve_vector(vector_id)
        except Exception:
            return None

    def get_metadata(self, vector_id: int) -> str:
        """
        Get metadata for a vector.

        Args:
            vector_id: Pattern ID

        Returns:
            Metadata string or empty string if not found
        """
        if not self._store:
            raise RuntimeError("Vector store not connected")

        try:
            return self._store.get_vector_metadata(vector_id)
        except Exception:
            return ""

    def get_stats(self) -> dict:
        """
        Get vector store statistics.

        Returns:
            Dict with store_path, vector_dim, num_clusters, file_size
        """
        stats = {
            "store_path": str(self.store_path),
            "vector_dim": self.vector_dim,
            "num_clusters": self.num_clusters,
            "file_size_mb": 0,
            "is_connected": self.is_connected,
        }

        if self.store_path.exists():
            stats["file_size_mb"] = round(
                self.store_path.stat().st_size / (1024 * 1024), 2
            )

        return stats
