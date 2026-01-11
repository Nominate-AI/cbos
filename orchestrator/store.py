"""Pattern store with vectl-backed similarity search"""

import logging
from pathlib import Path
from typing import Optional

from .config import settings
from .database import PatternDatabase
from .embeddings import CBAIClient
from .models import DecisionPattern, PatternMatch, PatternStats, QuestionType
from .vectors import VectorStore

logger = logging.getLogger(__name__)


class PatternStore:
    """
    Queryable store for decision patterns with similarity search.

    Uses SQLite for pattern metadata and vectl for vector storage/search.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        vector_store_path: Optional[Path] = None,
        cbai_url: Optional[str] = None,
    ):
        self.db = PatternDatabase(db_path)
        self.vectors = VectorStore(store_path=vector_store_path)
        self.cbai_client = CBAIClient(cbai_url)

    def connect(self) -> None:
        """Initialize database and vector store connections"""
        self.db.connect()
        self.vectors.connect()
        logger.info("PatternStore connected (SQLite + vectl)")

    def close(self) -> None:
        """Close all connections"""
        self.db.close()
        self.vectors.close()
        logger.info("PatternStore closed")

    def add_pattern(
        self, pattern: DecisionPattern, embedding: Optional[list[float]] = None
    ) -> int:
        """
        Add a pattern to the store.

        Args:
            pattern: The pattern to add
            embedding: Pre-computed embedding (optional)

        Returns:
            Pattern ID
        """
        # Insert pattern metadata into SQLite (without embedding)
        pattern_id = self.db.insert_pattern(pattern, embedding=None)

        # Store embedding in vectl if provided
        if embedding:
            metadata = pattern.question_text[:200]  # Store truncated question as metadata
            self.vectors.add_vector(pattern_id, embedding, metadata)

        return pattern_id

    async def add_pattern_with_embedding(self, pattern: DecisionPattern) -> int:
        """
        Add a pattern and generate its embedding.

        Args:
            pattern: The pattern to add

        Returns:
            Pattern ID
        """
        try:
            text_to_embed = f"{pattern.question_text}\n{pattern.context_before[:200]}"
            embedding = await self.cbai_client.embed(text_to_embed)

            if isinstance(embedding[0], list):
                embedding = embedding[0]

            return self.add_pattern(pattern, embedding)
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return self.add_pattern(pattern, None)

    async def add_patterns_batch(
        self,
        patterns: list[DecisionPattern],
        batch_size: int = None,
        generate_embeddings: bool = True,
    ) -> int:
        """
        Add multiple patterns efficiently with batched embedding generation.

        Args:
            patterns: List of patterns to add
            batch_size: Batch size for embedding generation
            generate_embeddings: Whether to generate embeddings

        Returns:
            Number of patterns added
        """
        batch_size = batch_size or settings.batch_size
        added = 0

        if generate_embeddings:
            # Generate embeddings in batches via CBAI
            texts = [
                f"{p.question_text}\n{p.context_before[:200]}" for p in patterns
            ]
            embeddings = await self.cbai_client.embed_batch(texts, batch_size)

            for pattern, embedding in zip(patterns, embeddings):
                try:
                    self.add_pattern(pattern, embedding)
                    added += 1
                except Exception as e:
                    logger.error(f"Failed to add pattern: {e}")
        else:
            for pattern in patterns:
                try:
                    self.add_pattern(pattern, None)
                    added += 1
                except Exception as e:
                    logger.error(f"Failed to add pattern: {e}")

        return added

    def query_similar(
        self,
        query_embedding: list[float],
        threshold: float = None,
        max_results: int = None,
        question_type: Optional[QuestionType] = None,
        project_filter: Optional[str] = None,
    ) -> list[PatternMatch]:
        """
        Find patterns similar to a query embedding using vectl K-means search.

        Args:
            query_embedding: The query embedding vector
            threshold: Minimum similarity threshold
            max_results: Maximum number of results
            question_type: Filter by question type
            project_filter: Filter by project name (substring)

        Returns:
            List of matches sorted by similarity descending
        """
        threshold = threshold or settings.similarity_threshold
        max_results = max_results or settings.max_query_results

        # Query vectl for similar vectors (get more than needed for filtering)
        k = max_results * 3  # Over-fetch to account for filters
        results = self.vectors.find_similar(query_embedding, k=k)

        matches = []
        for pattern_id, similarity in results:
            if similarity < threshold:
                continue

            pattern = self.db.get_pattern(pattern_id)
            if pattern is None:
                continue

            # Apply filters
            if question_type and pattern.question_type != question_type:
                continue
            if project_filter and project_filter.lower() not in pattern.project.lower():
                continue

            matches.append(PatternMatch(
                pattern=pattern,
                similarity=round(similarity, 4),
            ))

            if len(matches) >= max_results:
                break

        return matches

    async def query_similar_text(
        self,
        query_text: str,
        threshold: float = None,
        max_results: int = None,
        question_type: Optional[QuestionType] = None,
        project_filter: Optional[str] = None,
    ) -> list[PatternMatch]:
        """
        Find patterns similar to a query text.

        Generates embedding via CBAI and searches using vectl.

        Args:
            query_text: The query text
            threshold: Minimum similarity threshold
            max_results: Maximum number of results
            question_type: Filter by question type
            project_filter: Filter by project name

        Returns:
            List of matches sorted by similarity descending
        """
        # Generate embedding for query via CBAI
        embedding = await self.cbai_client.embed(query_text)

        if isinstance(embedding[0], list):
            embedding = embedding[0]

        return self.query_similar(
            query_embedding=embedding,
            threshold=threshold,
            max_results=max_results,
            question_type=question_type,
            project_filter=project_filter,
        )

    def search_text(self, query: str, limit: int = 20) -> list[DecisionPattern]:
        """
        Full-text search on question_text (SQLite LIKE).

        Args:
            query: Search query (substring match)
            limit: Maximum results

        Returns:
            List of matching patterns
        """
        return self.db.search_text(query, limit)

    def get_pattern(self, pattern_id: int) -> Optional[DecisionPattern]:
        """Get a pattern by ID"""
        return self.db.get_pattern(pattern_id)

    def get_stats(self) -> PatternStats:
        """Get statistics about the pattern store"""
        db_stats = self.db.get_stats()
        vector_stats = self.vectors.get_stats()

        return PatternStats(
            total_patterns=db_stats["total"],
            patterns_with_embeddings=db_stats["total"],  # All in vectl now
            question_types=db_stats["by_type"],
            projects=db_stats["by_project"],
            date_range=db_stats["date_range"],
        )

    def get_vector_stats(self) -> dict:
        """Get vectl-specific statistics"""
        return self.vectors.get_stats()

    async def rebuild_embeddings(self, batch_size: int = None) -> int:
        """
        Regenerate all embeddings via CBAI and store in vectl.

        Useful when changing embedding models.

        Returns:
            Number of embeddings generated
        """
        batch_size = batch_size or settings.batch_size
        patterns = self.db.get_all_patterns()

        texts = [
            f"{p.question_text}\n{p.context_before[:200]}" for p in patterns
        ]
        embeddings = await self.cbai_client.embed_batch(texts, batch_size)

        updated = 0
        for pattern, embedding in zip(patterns, embeddings):
            if embedding and pattern.id:
                metadata = pattern.question_text[:200]
                self.vectors.add_vector(pattern.id, embedding, metadata)
                updated += 1

        return updated
