"""Tests for ClaudeProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from artimanager.agent.claude import ClaudeProvider


class _FakeAnthropic:
    class AuthenticationError(Exception):
        pass

    class APIError(Exception):
        pass


class TestClaudeProviderBasics:
    def test_provider_id(self) -> None:
        provider = ClaudeProvider()
        assert provider.provider_id == "claude"

    def test_ensure_client_raises_when_sdk_missing(self) -> None:
        provider = ClaudeProvider()
        with patch(
            "artimanager.agent.claude.importlib.import_module",
            side_effect=ImportError("No module named anthropic"),
        ):
            with pytest.raises(RuntimeError, match="anthropic SDK is not installed"):
                provider._ensure_client()


class TestClaudeProviderFormatting:
    def test_format_paper_for_prompt(self) -> None:
        paper = {
            "title": "Test Title",
            "authors": ["Alice", "Bob"],
            "year": 2024,
            "abstract": "Short abstract",
            "full_text": "Body text",
        }
        text = ClaudeProvider._format_paper_for_prompt(paper)
        assert "Title: Test Title" in text
        assert "Authors: Alice, Bob" in text
        assert "Year: 2024" in text
        assert "Abstract: Short abstract" in text
        assert "Full text: Body text" in text

    def test_format_paper_for_prompt_truncates_long_full_text(self) -> None:
        paper = {"title": "T", "full_text": "x" * 50010}
        text = ClaudeProvider._format_paper_for_prompt(paper)
        assert "[truncated]" in text
        assert "Full text: " in text


class TestClaudeProviderCalls:
    def test_analyze_calls_messages_create(self) -> None:
        provider = ClaudeProvider(model="claude-test", api_key="secret")
        mock_create = MagicMock(
            return_value=SimpleNamespace(content=[SimpleNamespace(text="analysis result")])
        )
        provider._client = SimpleNamespace(messages=SimpleNamespace(create=mock_create))

        result = provider.analyze(
            {"title": "Test", "authors": ["A"], "year": 2024, "abstract": "Abs"},
            "focus on limitations",
        )

        assert result == "analysis result"
        kwargs = mock_create.call_args.kwargs
        assert kwargs["model"] == "claude-test"
        assert kwargs["max_tokens"] == 2048
        assert "Analysis focus: focus on limitations" in kwargs["messages"][0]["content"]

    def test_search_query_parses_multiline_output(self) -> None:
        provider = ClaudeProvider()
        mock_create = MagicMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(text="query one\n\nquery two\n  query three  ")]
            )
        )
        provider._client = SimpleNamespace(messages=SimpleNamespace(create=mock_create))

        result = provider.search_query("graph neural networks")
        assert result == ["query one", "query two", "query three"]

    def test_analyze_raises_invalid_api_key_on_auth_error(self) -> None:
        provider = ClaudeProvider()
        provider._anthropic = _FakeAnthropic
        provider._client = SimpleNamespace(
            messages=SimpleNamespace(
                create=MagicMock(side_effect=_FakeAnthropic.AuthenticationError("bad key"))
            )
        )
        with pytest.raises(RuntimeError, match="Invalid API key"):
            provider.analyze({"title": "x"}, "focus")

    def test_analyze_raises_runtime_error_on_api_error(self) -> None:
        provider = ClaudeProvider()
        provider._anthropic = _FakeAnthropic
        provider._client = SimpleNamespace(
            messages=SimpleNamespace(
                create=MagicMock(side_effect=_FakeAnthropic.APIError("timeout"))
            )
        )
        with pytest.raises(RuntimeError, match="Anthropic API error"):
            provider.analyze({"title": "x"}, "focus")
