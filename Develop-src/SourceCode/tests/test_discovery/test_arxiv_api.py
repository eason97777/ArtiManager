"""Tests for discovery.arxiv_api — Atom XML parsing."""

from __future__ import annotations

import responses

from artimanager.discovery.arxiv_api import search_by_topic

_ARXIV_API = "https://export.arxiv.org/api/query"

_SAMPLE_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.12345v1</id>
    <title>Test  arXiv  Paper  Title</title>
    <published>2023-01-15T00:00:00Z</published>
    <summary>This is a test abstract for the paper.</summary>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2302.54321v1</id>
    <title>Another  Paper</title>
    <published>2023-02-20T00:00:00Z</published>
    <summary>Another abstract.</summary>
    <author><name>Carol White</name></author>
  </entry>
</feed>"""


class TestSearchByTopic:
    @responses.activate
    def test_parses_entries(self) -> None:
        responses.add(
            responses.GET,
            _ARXIV_API,
            body=_SAMPLE_ATOM,
            status=200,
        )
        results = search_by_topic("quantum", max_results=10)
        assert len(results) == 2
        assert results[0].title == "Test arXiv Paper Title"
        assert results[0].arxiv_id == "2301.12345v1"
        assert results[0].year == 2023
        assert results[0].source == "arxiv"
        assert results[0].external_id == "2301.12345v1"
        assert len(results[0].authors) == 2
        assert "test abstract" in results[0].abstract

    @responses.activate
    def test_empty_feed(self) -> None:
        responses.add(
            responses.GET,
            _ARXIV_API,
            body='<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
            status=200,
        )
        results = search_by_topic("nothing")
        assert results == []

    @responses.activate
    def test_api_error_returns_empty(self) -> None:
        responses.add(
            responses.GET,
            _ARXIV_API,
            body="Server Error",
            status=500,
        )
        results = search_by_topic("error")
        assert results == []
