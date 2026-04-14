"""Semantic Scholar API adapter.

Free tier: 100 requests / 5 minutes.
Base URL: https://api.semanticscholar.org/graph/v1
"""

from __future__ import annotations

import logging
from typing import Any

from artimanager.discovery._http import http_get
from artimanager.discovery._models import ExternalPaper

logger = logging.getLogger(__name__)

_S2_BASE = "https://api.semanticscholar.org/graph/v1"

_PAPER_FIELDS = (
    "title,authors,year,abstract,externalIds,citationCount,venue,url"
)


def _extract_doi(external_ids: dict | None) -> str | None:
    if not external_ids:
        return None
    return external_ids.get("DOI")


def _extract_arxiv(external_ids: dict | None) -> str | None:
    if not external_ids:
        return None
    return external_ids.get("ArXivId")


def _parse_s2_author(author: dict) -> str:
    return author.get("name", "")


def _parse_s2_paper(raw: dict[str, Any]) -> ExternalPaper:
    """Convert a raw S2 paper JSON into ExternalPaper."""
    ext_ids = raw.get("externalIds")
    doi = _extract_doi(ext_ids)
    arxiv_id = _extract_arxiv(ext_ids)
    external_id = doi or arxiv_id or ""

    authors_raw = raw.get("authors") or []
    authors = [_parse_s2_author(a) for a in authors_raw if a.get("name")]

    return ExternalPaper(
        title=raw.get("title") or "",
        authors=authors,
        year=raw.get("year"),
        abstract=raw.get("abstract") or "",
        doi=doi,
        arxiv_id=arxiv_id,
        venue=raw.get("venue"),
        url=raw.get("url"),
        citation_count=raw.get("citationCount"),
        source="semantic_scholar",
        external_id=external_id,
    )


def get_paper_by_doi(doi: str) -> ExternalPaper | None:
    """Look up a paper on S2 by DOI."""
    url = f"{_S2_BASE}/paper/DOI:{doi}"
    data = http_get(url, params={"fields": _PAPER_FIELDS})
    if data is None:
        return None
    return _parse_s2_paper(data)


def get_paper_by_arxiv(arxiv_id: str) -> ExternalPaper | None:
    """Look up a paper on S2 by arXiv ID.

    S2 API does not accept the ``vN`` version suffix, so we strip it.
    """
    # Strip version suffix (e.g. "1803.02029v1" -> "1803.02029")
    base_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
    url = f"{_S2_BASE}/paper/ARXIV:{base_id}"
    data = http_get(url, params={"fields": _PAPER_FIELDS})
    if data is None:
        return None
    return _parse_s2_paper(data)


def get_references(s2_paper_id: str, limit: int = 20) -> list[ExternalPaper]:
    """Get papers that the given paper cites (references)."""
    url = f"{_S2_BASE}/paper/{s2_paper_id}/references"
    data = http_get(url, params={
        "fields": f"citedPaper.title,citedPaper.authors,citedPaper.year,"
                  f"citedPaper.abstract,citedPaper.externalIds,"
                  f"citedPaper.citationCount,citedPaper.venue,citedPaper.url",
        "limit": limit,
    })
    if data is None:
        return []

    results: list[ExternalPaper] = []
    for item in data.get("data", []):
        cited = item.get("citedPaper")
        if cited:
            results.append(_parse_s2_paper(cited))
    return results


def get_citations(s2_paper_id: str, limit: int = 20) -> list[ExternalPaper]:
    """Get papers that cite the given paper."""
    url = f"{_S2_BASE}/paper/{s2_paper_id}/citations"
    data = http_get(url, params={
        "fields": f"citingPaper.title,citingPaper.authors,citingPaper.year,"
                  f"citingPaper.abstract,citingPaper.externalIds,"
                  f"citingPaper.citationCount,citingPaper.venue,citingPaper.url",
        "limit": limit,
    })
    if data is None:
        return []

    results: list[ExternalPaper] = []
    for item in data.get("data", []):
        citing = item.get("citingPaper")
        if citing:
            results.append(_parse_s2_paper(citing))
    return results


def search_by_query(query: str, limit: int = 20) -> list[ExternalPaper]:
    """Search S2 by free-text query."""
    url = f"{_S2_BASE}/paper/search"
    data = http_get(url, params={
        "query": query,
        "fields": _PAPER_FIELDS,
        "limit": limit,
    })
    if data is None:
        return []

    return [_parse_s2_paper(p) for p in data.get("data", [])]
