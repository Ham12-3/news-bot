"""
AI client for LLM API calls.
Supports OpenAI and Anthropic APIs with automatic fallback.
"""

import json
from typing import Any
from enum import Enum

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ModelTier(str, Enum):
    """Model tiers for different use cases."""
    CHEAP = "cheap"  # Fast, cheap - for scoring
    STRONG = "strong"  # Best quality - for briefings


# Model mappings
OPENAI_MODELS = {
    ModelTier.CHEAP: "gpt-4o-mini",
    ModelTier.STRONG: "gpt-4o",
}

ANTHROPIC_MODELS = {
    ModelTier.CHEAP: "claude-3-haiku-20240307",
    ModelTier.STRONG: "claude-3-5-sonnet-20241022",
}


class AIClient:
    """Unified AI client supporting multiple providers."""

    def __init__(self):
        self.timeout = 30
        self._provider = self._detect_provider()

    def _detect_provider(self) -> str:
        """Detect which AI provider to use based on available keys."""
        if settings.ANTHROPIC_API_KEY:
            return "anthropic"
        elif settings.OPENAI_API_KEY:
            return "openai"
        else:
            logger.warning("No AI API keys configured")
            return "none"

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        tier: ModelTier = ModelTier.CHEAP,
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> str:
        """
        Get a completion from the AI model.

        Args:
            system_prompt: System-level instructions
            user_prompt: User message / actual prompt
            tier: Model tier to use (cheap for scoring, strong for briefings)
            max_tokens: Maximum response tokens
            temperature: Sampling temperature

        Returns:
            The model's response text
        """
        if self._provider == "anthropic":
            return await self._complete_anthropic(
                system_prompt, user_prompt, tier, max_tokens, temperature
            )
        elif self._provider == "openai":
            return await self._complete_openai(
                system_prompt, user_prompt, tier, max_tokens, temperature
            )
        else:
            raise ValueError("No AI provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY")

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        tier: ModelTier = ModelTier.CHEAP,
        max_tokens: int = 500,
    ) -> dict[str, Any]:
        """Get a JSON completion from the AI model."""
        response = await self.complete(
            system_prompt=system_prompt + "\n\nRespond with valid JSON only.",
            user_prompt=user_prompt,
            tier=tier,
            max_tokens=max_tokens,
            temperature=0.1,  # Lower temp for structured output
        )

        # Parse JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            return json.loads(response.strip())
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {response}")
            return {"error": "Failed to parse response", "raw": response}

    async def _complete_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        tier: ModelTier,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Call Anthropic API."""
        model = ANTHROPIC_MODELS[tier]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    async def _complete_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        tier: ModelTier,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Call OpenAI API."""
        model = OPENAI_MODELS[tier]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]


# Singleton instance
_ai_client: AIClient | None = None


def get_ai_client() -> AIClient:
    """Get the AI client singleton."""
    global _ai_client
    if _ai_client is None:
        _ai_client = AIClient()
    return _ai_client
