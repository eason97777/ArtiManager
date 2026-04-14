"""Tests for LocalProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from artimanager.agent.local import LocalProvider


class TestLocalProvider:
    def test_provider_id(self) -> None:
        provider = LocalProvider(model="llama3")
        assert provider.provider_id == "local"

    def test_analyze_calls_ollama_style_endpoint(self) -> None:
        provider = LocalProvider(model="llama3", endpoint="http://localhost:11434", timeout_seconds=22)
        mock_resp = SimpleNamespace(ok=True, json=lambda: {"response": "analysis output"})
        with patch("artimanager.agent.local.requests.post", return_value=mock_resp) as mock_post:
            out = provider.analyze({"title": "T", "authors": ["A"], "year": 2024, "abstract": "Abs"}, "focus")

        assert out == "analysis output"
        kwargs = mock_post.call_args.kwargs
        assert kwargs["timeout"] == 22
        assert kwargs["json"]["model"] == "llama3"
        assert kwargs["json"]["stream"] is False
        assert "Analysis focus: focus" in kwargs["json"]["prompt"]

    def test_search_query_parses_lines(self) -> None:
        provider = LocalProvider(model="llama3")
        with patch.object(provider, "_call_local_backend", return_value="q1\n\n q2 \n"):
            assert provider.search_query("topic") == ["q1", "q2"]

    def test_service_unavailable_maps_to_runtime_error(self) -> None:
        provider = LocalProvider(model="llama3")
        with patch(
            "artimanager.agent.local.requests.post",
            side_effect=requests.RequestException("connection refused"),
        ):
            with pytest.raises(RuntimeError, match="backend unavailable"):
                provider.summarize("text")

    def test_backend_error_status_maps_to_runtime_error(self) -> None:
        provider = LocalProvider(model="llama3")
        mock_resp = SimpleNamespace(ok=False, status_code=500, json=lambda: {"error": "model not found"}, text="")
        with patch("artimanager.agent.local.requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="model not found"):
                provider.summarize("text")

    def test_malformed_response_maps_to_runtime_error(self) -> None:
        provider = LocalProvider(model="llama3")
        mock_resp = SimpleNamespace(ok=True, json=lambda: {"unexpected": "shape"})
        with patch("artimanager.agent.local.requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="malformed response payload"):
                provider.summarize("text")

    def test_missing_model_fails_clearly(self) -> None:
        provider = LocalProvider(model="")
        with pytest.raises(RuntimeError, match="Local model is not configured"):
            provider.summarize("text")
