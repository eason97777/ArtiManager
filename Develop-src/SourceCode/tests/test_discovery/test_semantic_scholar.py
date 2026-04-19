"""Tests for discovery.semantic_scholar — API response parsing."""

from __future__ import annotations

import responses

from artimanager.discovery.semantic_scholar import (
    get_citations,
    get_paper_by_doi,
    get_references,
    semantic_scholar_identifier_for_arxiv,
    search_by_query,
)

_S2_BASE = "https://api.semanticscholar.org/graph/v1"


def _s2_paper_json(
    paper_id: str = "1",
    title: str = "Test Paper",
    doi: str | None = "10.1234/test",
    arxiv_id: str | None = None,
    year: int = 2023,
    citation_count: int = 10,
) -> dict:
    ext_ids: dict = {}
    if doi:
        ext_ids["DOI"] = doi
    if arxiv_id:
        ext_ids["ArXivId"] = arxiv_id
    return {
        "paperId": paper_id,
        "title": title,
        "authors": [{"name": "Alice Smith"}, {"name": "Bob Jones"}],
        "year": year,
        "abstract": "A test abstract.",
        "externalIds": ext_ids,
        "citationCount": citation_count,
        "venue": "TestConf",
        "url": f"https://example.com/{paper_id}",
    }


class TestGetPaperByDoi:
    @responses.activate
    def test_success(self) -> None:
        responses.add(
            responses.GET,
            f"{_S2_BASE}/paper/DOI%3A10.1234%2Ftest",
            json=_s2_paper_json(),
            status=200,
        )
        result = get_paper_by_doi("10.1234/test")
        assert result is not None
        assert result.title == "Test Paper"
        assert result.source == "semantic_scholar"
        assert result.external_id == "1"
        assert result.doi == "10.1234/test"
        assert len(result.authors) == 2

    @responses.activate
    def test_not_found(self) -> None:
        responses.add(
            responses.GET,
            f"{_S2_BASE}/paper/DOI%3A10.9999%2Fnope",
            json={"error": "not found"},
            status=404,
        )
        result = get_paper_by_doi("10.9999/nope")
        assert result is None


class TestGetReferences:
    @responses.activate
    def test_returns_cited_papers(self) -> None:
        responses.add(
            responses.GET,
            f"{_S2_BASE}/paper/p1/references",
            json={
                "data": [
                    {"citedPaper": _s2_paper_json("ref1", "Ref Paper 1", doi="10.1/ref1")},
                    {"citedPaper": _s2_paper_json("ref2", "Ref Paper 2", doi="10.1/ref2")},
                ]
            },
            status=200,
        )
        results = get_references("p1")
        assert len(results) == 2
        assert results[0].title == "Ref Paper 1"
        assert results[0].source == "semantic_scholar"
        assert results[0].external_id == "ref1"

    @responses.activate
    def test_quotes_doi_anchor_path(self) -> None:
        responses.add(
            responses.GET,
            f"{_S2_BASE}/paper/DOI%3A10.1234%2Fslash/references",
            json={"data": []},
            status=200,
        )
        results = get_references("DOI:10.1234/slash")
        assert results == []

    @responses.activate
    def test_quotes_arxiv_anchor_path(self) -> None:
        responses.add(
            responses.GET,
            f"{_S2_BASE}/paper/ARXIV%3A2401.00001/references",
            json={"data": []},
            status=200,
        )
        results = get_references(semantic_scholar_identifier_for_arxiv("2401.00001v2"))
        assert results == []


class TestGetCitations:
    @responses.activate
    def test_returns_citing_papers(self) -> None:
        responses.add(
            responses.GET,
            f"{_S2_BASE}/paper/p1/citations",
            json={
                "data": [
                    {"citingPaper": _s2_paper_json("cit1", "Citing Paper", doi="10.1/cit1")},
                ]
            },
            status=200,
        )
        results = get_citations("p1")
        assert len(results) == 1
        assert results[0].title == "Citing Paper"


class TestSearchByQuery:
    @responses.activate
    def test_returns_papers(self) -> None:
        responses.add(
            responses.GET,
            f"{_S2_BASE}/paper/search",
            json={
                "data": [
                    _s2_paper_json("s1", "Search Result 1", doi="10.1/s1"),
                    _s2_paper_json("s2", "Search Result 2", doi="10.1/s2"),
                ],
                "total": 2,
            },
            status=200,
        )
        results = search_by_query("machine learning")
        assert len(results) == 2
        assert results[0].title == "Search Result 1"

    @responses.activate
    def test_paper_id_is_candidate_identity_when_no_external_ids(self) -> None:
        responses.add(
            responses.GET,
            f"{_S2_BASE}/paper/search",
            json={
                "data": [
                    _s2_paper_json("s2-only", "S2 Only", doi=None, arxiv_id=None),
                ],
                "total": 1,
            },
            status=200,
        )
        results = search_by_query("machine learning")
        assert len(results) == 1
        assert results[0].external_id == "s2-only"
        assert results[0].doi is None
        assert results[0].arxiv_id is None
