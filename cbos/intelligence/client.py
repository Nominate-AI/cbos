"""CBAI API client wrapper"""

import json
import logging
from typing import Optional, AsyncIterator

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class CBAIClient:
    """Client for the CBAI unified AI service"""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.cbai_url).rstrip("/")
        self.timeout = settings.request_timeout

    async def chat(
        self,
        messages: list[dict],
        provider: str = "ollama",
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """
        Send a chat request to CBAI.

        Args:
            messages: List of message dicts with 'role' and 'content'
            provider: 'ollama' or 'claude'
            model: Model override (uses provider default if not specified)
            temperature: Sampling temperature (0.0-2.0)
            max_tokens: Max response tokens
            stream: Whether to stream the response

        Returns:
            Response text or async iterator of chunks if streaming
        """
        payload = {
            "messages": messages,
            "provider": provider,
            "temperature": temperature,
            "stream": stream,
        }

        if model:
            payload["model"] = model
        if max_tokens:
            payload["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if stream:
                return self._stream_chat(client, payload)
            else:
                response = await client.post(
                    f"{self.base_url}/api/v1/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("content", "")

    async def _stream_chat(
        self, client: httpx.AsyncClient, payload: dict
    ) -> AsyncIterator[str]:
        """Stream chat response chunks"""
        async with client.stream(
            "POST",
            f"{self.base_url}/api/v1/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_text():
                yield chunk

    async def summarize(
        self,
        text: str,
        max_length: int = 200,
        style: str = "concise",
    ) -> str:
        """
        Summarize text using CBAI.

        Args:
            text: Text to summarize
            max_length: Maximum summary length in words
            style: Summary style ('concise', 'detailed', 'bullets')

        Returns:
            Summary text
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/summarize",
                json={
                    "text": text,
                    "max_length": max_length,
                    "style": style,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("summary", "")

    async def topics(self, text: str) -> list[str]:
        """
        Extract topics from text.

        Args:
            text: Text to analyze

        Returns:
            List of 3-5 topic strings
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/topics",
                json={"text": text},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("topics", [])

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

    async def chat_json(
        self,
        messages: list[dict],
        provider: str = "ollama",
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> dict:
        """
        Chat expecting JSON response. Parses and returns dict.

        Uses lower temperature for more consistent JSON output.
        """
        response = await self.chat(
            messages=messages,
            provider=provider,
            model=model,
            temperature=temperature,
            stream=False,
        )

        # Try to extract JSON from response
        text = response.strip()

        # Handle markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {text}")
            # Return a default structure
            return {"error": "Failed to parse response", "raw": text}
