"""OpenAI agent provider (stub)."""

from __future__ import annotations

from typing import Any

from artimanager.agent.base import AgentProvider


class OpenAIProvider(AgentProvider):
    """Agent provider placeholder for a future OpenAI SDK integration."""

    def __init__(self, model: str = "", api_key: str = "") -> None:
        self._model = model
        self._api_key = api_key

    @property
    def provider_id(self) -> str:
        return "openai"

    def analyze(self, paper: dict[str, Any], prompt: str) -> str:
        raise NotImplementedError("OpenAIProvider is not yet implemented")

    def compare(self, papers: list[dict[str, Any]], prompt: str) -> str:
        raise NotImplementedError("OpenAIProvider is not yet implemented")

    def search_query(self, topic: str) -> list[str]:
        raise NotImplementedError("OpenAIProvider is not yet implemented")

    def summarize(self, text: str) -> str:
        raise NotImplementedError("OpenAIProvider is not yet implemented")
