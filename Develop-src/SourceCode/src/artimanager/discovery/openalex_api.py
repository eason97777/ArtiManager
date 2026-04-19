"""OpenAlex API adapter for author-identity work discovery."""

from __future__ import annotations

import re
from typing import Any

from artimanager.discovery._http import http_get
from artimanager.discovery._models import ExternalPaper

_OPENALEX_BASE = "https://api.openalex.org"
_OPENALEX_AUTHOR_RE = re.compile(r"^A\d+$")
_ARXIV_ABS_PREFIX = "https://arxiv.org/abs/"
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/")


def normalize_openalex_author_id(raw: str) -> str:
    """Normalize an OpenAlex author ID to full URL form."""
    value = raw.strip().rstrip("/")
    if not value:
        raise ValueError("OpenAlex author_id is required")
    if value.startswith("https://openalex.org/"):
        author_key = value.rsplit("/", 1)[-1]
    elif value.startswith("http://openalex.org/"):
        author_key = value.rsplit("/", 1)[-1]
    else:
        author_key = value
    if not _OPENALEX_AUTHOR_RE.fullmatch(author_key):
        raise ValueError("OpenAlex author_id must be a stable ID such as A123456789")
    return f"https://openalex.org/{author_key}"


def _normalize_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    lower = value.lower()
    for prefix in _DOI_PREFIXES:
        if lower.startswith(prefix):
            return value[len(prefix):]
    return value


def _normalize_arxiv(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if value.startswith(_ARXIV_ABS_PREFIX):
        return value[len(_ARXIV_ABS_PREFIX):]
    return value


def _abstract_from_inverted_index(raw: dict[str, list[int]] | None) -> str:
    if not raw:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in raw.items():
        for index in indexes:
            positions.append((index, word))
    return " ".join(word for _, word in sorted(positions))


def _parse_openalex_work(raw: dict[str, Any]) -> ExternalPaper:
    ids = raw.get("ids") or {}
    openalex_id = raw.get("id") or ids.get("openalex") or ""
    doi = _normalize_doi(raw.get("doi") or ids.get("doi"))
    arxiv_id = _normalize_arxiv(ids.get("arxiv"))
    authors: list[str] = []
    for authorship in raw.get("authorships") or []:
        author = authorship.get("author") or {}
        display_name = author.get("display_name")
        if display_name:
            authors.append(display_name)

    return ExternalPaper(
        title=raw.get("display_name") or raw.get("title") or "",
        authors=authors,
        year=raw.get("publication_year"),
        abstract=_abstract_from_inverted_index(raw.get("abstract_inverted_index")),
        doi=doi,
        arxiv_id=arxiv_id,
        venue=(raw.get("primary_location") or {}).get("source", {}).get("display_name"),
        url=openalex_id or None,
        citation_count=raw.get("cited_by_count"),
        source="openalex",
        external_id=openalex_id,
    )


def get_works_by_author(author_id: str, *, limit: int = 20) -> list[ExternalPaper]:
    """Fetch works for one normalized OpenAlex author identity."""
    normalized = normalize_openalex_author_id(author_id)
    capped_limit = max(1, min(100, int(limit)))
    data = http_get(
        f"{_OPENALEX_BASE}/works",
        params={
            "filter": f"authorships.author.id:{normalized}",
            "per-page": capped_limit,
            "sort": "publication_year:desc",
        },
    )
    if data is None:
        return []
    return [_parse_openalex_work(item) for item in data.get("results", [])]
