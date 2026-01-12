"""Embedding client and similarity functions for the CBOS Orchestrator

Ported from archive/cbos/intelligence/client.py and embeddings.py
"""

import logging
import math

import httpx

from .config import settings

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors"""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class CBAIClient:
    """Client for the CBAI unified AI service - embedding functionality"""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.cbai_url).rstrip("/")
        self.timeout = settings.request_timeout

    async def embed(self, text: str | list[str]) -> list[float] | list[list[float]]:
        """
        Generate embeddings for text.

        Args:
            text: Single string or list of strings

        Returns:
            768-dim embedding vector(s)
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/embed",
                json={"text": text},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("embedding") or data.get("embeddings", [])

    async def embed_batch(
        self, texts: list[str], batch_size: int = 50
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batches.

        Args:
            texts: List of strings to embed
            batch_size: Number of texts per batch

        Returns:
            List of 768-dim embedding vectors
        """
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                result = await self.embed(batch)
                # Handle both single and batch responses
                if isinstance(result[0], float):
                    # Single embedding returned as flat list
                    all_embeddings.append(result)
                else:
                    # Batch of embeddings
                    all_embeddings.extend(result)
            except Exception as e:
                logger.error(f"Failed to embed batch {i}-{i + len(batch)}: {e}")
                # Add None placeholders for failed embeddings
                all_embeddings.extend([None] * len(batch))

        return all_embeddings

    async def health(self) -> dict:
        """Check CBAI service health"""
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{self.base_url}/api/v1/health")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"CBAI health check failed: {e}")
                return {"status": "error", "error": str(e)}
