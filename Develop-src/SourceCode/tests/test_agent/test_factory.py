"""Tests for agent provider factory."""

from __future__ import annotations

import pytest

from artimanager.agent.claude import ClaudeProvider
from artimanager.agent.factory import create_provider
from artimanager.agent.local import LocalProvider
from artimanager.agent.mock import MockProvider
from artimanager.agent.openai_provider import OpenAIProvider
from artimanager.config import AgentConfig


class TestCreateProvider:
    def test_returns_mock_provider(self) -> None:
        provider = create_provider(AgentConfig(provider="mock"))
        assert isinstance(provider, MockProvider)

    def test_returns_claude_provider(self) -> None:
        provider = create_provider(AgentConfig(provider="claude", model="claude-abc"))
        assert isinstance(provider, ClaudeProvider)
        assert provider.provider_id == "claude"

    def test_returns_openai_provider(self) -> None:
        provider = create_provider(AgentConfig(provider="openai", model="gpt-test"))
        assert isinstance(provider, OpenAIProvider)
        assert provider.provider_id == "openai"

    def test_returns_local_provider(self) -> None:
        provider = create_provider(AgentConfig(provider="local", model="llama"))
        assert isinstance(provider, LocalProvider)
        assert provider.provider_id == "local"

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown agent provider"):
            create_provider(AgentConfig(provider="unknown"))
