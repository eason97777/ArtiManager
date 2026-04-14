"""Tests for discovery.deepxiv_api."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import responses

from artimanager.config import DeepXivConfig
from artimanager.discovery._http import HttpJsonResult
from artimanager.discovery.deepxiv_api import search_by_topic


def _cfg(*, enabled: bool = True) -> DeepXivConfig:
    return DeepXivConfig(
        enabled=enabled,
        api_token_env="DEEPXIV_TOKEN",
        base_url="https://data.rag.ac.cn/arxiv/",
        timeout_seconds=20,
        search_mode="hybrid",
    )


@responses.activate
def test_search_maps_results(monkeypatch) -> None:
    monkeypatch.setenv("DEEPXIV_TOKEN", "token-1")
    responses.add(
        responses.POST,
        "https://data.rag.ac.cn/arxiv/",
        json={
            "results": [
                {
                    "id": "dx-1",
                    "title": "DeepXiv Graph Paper",
                    "authors": [{"name": "Alice"}, {"name": "Bob"}],
                    "abstract": "A deepxiv abstract.",
                    "doi": "10.1234/dx",
                    "arxiv_id": "2401.12345v1",
                    "year": 2024,
                    "citation": 123,
                    "url": "https://arxiv.org/abs/2401.12345v1",
                }
            ]
        },
        status=200,
    )
    items = search_by_topic("graph neural networks", _cfg(), limit=5)
    assert len(items) == 1
    p = items[0]
    assert p.source == "deepxiv_arxiv"
    assert p.title == "DeepXiv Graph Paper"
    assert p.doi == "10.1234/dx"
    assert p.arxiv_id == "2401.12345v1"
    assert p.external_id == "10.1234/dx"
    assert p.year == 2024
    assert p.citation_count == 123

    req = responses.calls[0].request
    assert req.method == "POST"
    assert req.headers.get("Authorization") == "Bearer token-1"
    parsed = urlparse(req.url)
    q = parse_qs(parsed.query)
    assert q["type"] == ["retrieve"]
    assert q["query"] == ["graph neural networks"]
    assert q["size"] == ["5"]
    assert q["offset"] == ["0"]
    assert q["search_mode"] == ["hybrid"]


def test_search_http_failure_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.setenv("DEEPXIV_TOKEN", "token-1")
    monkeypatch.setattr(
        "artimanager.discovery.deepxiv_api.http_post_json_result",
        lambda *a, **k: HttpJsonResult(status_code=None, error="network failure"),
    )
    try:
        search_by_topic("graph", _cfg())
        assert False, "Expected RuntimeError for DeepXiv HTTP failure"
    except RuntimeError as exc:
        assert "request failed" in str(exc)


def test_search_empty_payload_returns_empty(monkeypatch) -> None:
    monkeypatch.setenv("DEEPXIV_TOKEN", "token-1")
    monkeypatch.setattr(
        "artimanager.discovery.deepxiv_api.http_post_json_result",
        lambda *a, **k: HttpJsonResult(status_code=200, payload={"results": []}),
    )
    items = search_by_topic("graph", _cfg())
    assert items == []


@responses.activate
def test_post_405_falls_back_to_get(monkeypatch) -> None:
    monkeypatch.setenv("DEEPXIV_TOKEN", "token-1")
    responses.add(
        responses.POST,
        "https://data.rag.ac.cn/arxiv/",
        json={"detail": "Method Not Allowed"},
        status=405,
    )
    responses.add(
        responses.GET,
        "https://data.rag.ac.cn/arxiv/",
        json={
            "results": [
                {
                    "id": "dx-get-1",
                    "title": "GET DeepXiv Paper",
                    "authors": ["Alice"],
                    "abstract": "A fallback result.",
                    "arxiv_id": "2402.12345",
                    "year": 2024,
                }
            ]
        },
        status=200,
    )

    items = search_by_topic("graph fallback", _cfg(), limit=3)

    assert len(items) == 1
    assert items[0].title == "GET DeepXiv Paper"
    assert items[0].source == "deepxiv_arxiv"
    assert responses.calls[0].request.method == "POST"
    assert responses.calls[1].request.method == "GET"
    parsed = urlparse(responses.calls[1].request.url)
    q = parse_qs(parsed.query)
    assert q["type"] == ["retrieve"]
    assert q["query"] == ["graph fallback"]
    assert q["size"] == ["3"]
    assert q["search_mode"] == ["hybrid"]


@responses.activate
def test_post_405_get_503_raises_clear_runtime_error(monkeypatch) -> None:
    monkeypatch.setenv("DEEPXIV_TOKEN", "token-1")
    monkeypatch.setattr("artimanager.discovery._http.time.sleep", lambda *_: None)
    responses.add(
        responses.POST,
        "https://data.rag.ac.cn/arxiv/",
        json={"detail": "Method Not Allowed"},
        status=405,
    )
    for _ in range(3):
        responses.add(
            responses.GET,
            "https://data.rag.ac.cn/arxiv/",
            json={"detail": "Bad Gateway"},
            status=503,
        )

    with pytest.raises(RuntimeError, match="HTTP 503"):
        search_by_topic("graph fallback", _cfg(), limit=3)


def test_missing_token_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.delenv("DEEPXIV_TOKEN", raising=False)
    try:
        search_by_topic("graph", _cfg())
        assert False, "Expected RuntimeError for missing DeepXiv token"
    except RuntimeError as exc:
        assert "token" in str(exc).lower()


def test_disabled_config_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.setenv("DEEPXIV_TOKEN", "token-1")
    try:
        search_by_topic("graph", _cfg(enabled=False))
        assert False, "Expected RuntimeError for disabled DeepXiv"
    except RuntimeError as exc:
        assert "disabled" in str(exc).lower()
