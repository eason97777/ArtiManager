"""Tests for MockProvider."""

from __future__ import annotations

from artimanager.agent.mock import MockProvider
from artimanager.agent.base import AgentProvider


class TestMockProviderInterface:
    def test_is_agent_provider(self) -> None:
        p = MockProvider()
        assert isinstance(p, AgentProvider)

    def test_provider_id(self) -> None:
        p = MockProvider()
        assert p.provider_id == "mock"


class TestMockProviderDefaults:
    def test_analyze_returns_string(self) -> None:
        p = MockProvider()
        result = p.analyze({"paper_id": "p1", "title": "Test"}, "summarize")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_compare_returns_string(self) -> None:
        p = MockProvider()
        result = p.compare([{"paper_id": "p1"}, {"paper_id": "p2"}], "compare")
        assert isinstance(result, str)

    def test_search_query_returns_list(self) -> None:
        p = MockProvider()
        result = p.search_query("transformer architectures")
        assert isinstance(result, list)
        assert all(isinstance(q, str) for q in result)

    def test_summarize_returns_string(self) -> None:
        p = MockProvider()
        result = p.summarize("Some long text about a paper.")
        assert isinstance(result, str)


class TestMockProviderCustomResponses:
    def test_override_analyze(self) -> None:
        p = MockProvider(responses={"analyze": "custom analysis"})
        assert p.analyze({}, "") == "custom analysis"

    def test_override_does_not_affect_others(self) -> None:
        p = MockProvider(responses={"analyze": "custom"})
        # summarize should still return default
        assert "[Mock summary]" in p.summarize("text")


class TestMockProviderCallLog:
    def test_records_calls(self) -> None:
        p = MockProvider()
        p.summarize("hello")
        p.analyze({"paper_id": "p1"}, "go")
        assert len(p.call_log) == 2
        assert p.call_log[0][0] == "summarize"
        assert p.call_log[1][0] == "analyze"

    def test_call_log_starts_empty(self) -> None:
        p = MockProvider()
        assert p.call_log == []
