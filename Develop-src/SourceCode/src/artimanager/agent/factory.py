"""Agent provider factory."""

from __future__ import annotations

from artimanager.agent.base import AgentProvider
from artimanager.agent.claude import ClaudeProvider
from artimanager.agent.local import LocalProvider
from artimanager.agent.mock import MockProvider
from artimanager.agent.openai_provider import OpenAIProvider
from artimanager.config import AgentConfig


def create_provider(config: AgentConfig) -> AgentProvider:
    """Instantiate an agent provider from AgentConfig."""
    provider = config.provider
    if provider == "mock":
        return MockProvider()
    if provider == "claude":
        return ClaudeProvider(
            model=config.model or "claude-sonnet-4-20250514",
            api_key=config.api_key or "",
        )
    if provider == "openai":
        return OpenAIProvider(
            model=config.model,
            api_key=config.api_key or "",
        )
    if provider == "local":
        return LocalProvider(model=config.model)
    raise ValueError(f"Unknown agent provider: {provider!r}")
