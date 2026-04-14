"""Tests for OpenAIProvider stub."""

from __future__ import annotations

import pytest

from artimanager.agent.openai_provider import OpenAIProvider


class TestOpenAIProvider:
    def test_provider_id(self) -> None:
        provider = OpenAIProvider(model="gpt-test")
        assert provider.provider_id == "openai"

    def test_methods_raise_not_implemented(self) -> None:
        provider = OpenAIProvider()
        with pytest.raises(NotImplementedError):
            provider.analyze({}, "")
        with pytest.raises(NotImplementedError):
            provider.compare([], "")
        with pytest.raises(NotImplementedError):
            provider.search_query("")
        with pytest.raises(NotImplementedError):
            provider.summarize("")
