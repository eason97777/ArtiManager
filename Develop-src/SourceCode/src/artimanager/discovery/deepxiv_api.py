"""DeepXiv REST adapter for topic discovery."""

from __future__ import annotations

import re
from typing import Any

from artimanager.config import DeepXivConfig
from artimanager.discovery._http import (
    HttpJsonResult,
    http_get_json_result,
    http_post_json_result,
)
from artimanager.discovery._models import ExternalPaper

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5}(?:v\d+)?)")


def _extract_year(raw: Any) -> int | None:
    if isinstance(raw, int):
        return raw
    if raw is None:
        return None
    text = str(raw)
    m = _YEAR_RE.search(text)
    if m is None:
        return None
    return int(m.group(1))


def _extract_doi(item: dict[str, Any]) -> str | None:
    value = item.get("doi") or item.get("DOI")
    if value:
        return str(value)
    ext = item.get("external_ids") or item.get("externalIds")
    if isinstance(ext, dict):
        value = ext.get("doi") or ext.get("DOI")
        if value:
            return str(value)
    return None


def _extract_arxiv_id(item: dict[str, Any]) -> str | None:
    direct = (
        item.get("arxiv_id")
        or item.get("arxivId")
        or item.get("ArXivId")
        or item.get("arxiv")
    )
    if direct:
        text = str(direct)
        m = _ARXIV_RE.search(text)
        return m.group(1) if m else text

    ext = item.get("external_ids") or item.get("externalIds")
    if isinstance(ext, dict):
        value = ext.get("arxiv") or ext.get("ArXivId") or ext.get("arxiv_id")
        if value:
            text = str(value)
            m = _ARXIV_RE.search(text)
            return m.group(1) if m else text

    for key in ("id", "paper_id", "external_id", "url"):
        value = item.get(key)
        if not value:
            continue
        text = str(value)
        m = _ARXIV_RE.search(text)
        if m:
            return m.group(1)
    return None


def _extract_authors(item: dict[str, Any]) -> list[str]:
    authors_raw = item.get("authors") or item.get("author") or []
    if isinstance(authors_raw, list):
        output: list[str] = []
        for author in authors_raw:
            if isinstance(author, str):
                text = author.strip()
            elif isinstance(author, dict):
                text = str(
                    author.get("name")
                    or author.get("author")
                    or author.get("full_name")
                    or ""
                ).strip()
            else:
                text = str(author).strip()
            if text:
                output.append(text)
        return output
    if isinstance(authors_raw, str):
        return [part.strip() for part in authors_raw.split(",") if part.strip()]
    return []


def _extract_results(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("results", "data", "items", "papers"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_citation_count(item: dict[str, Any]) -> int | None:
    value = item.get("citation")
    if value is None:
        value = item.get("citations")
    if value is None:
        value = item.get("citation_count")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _external_id(item: dict[str, Any], doi: str | None, arxiv_id: str | None) -> str:
    if doi:
        return doi
    if arxiv_id:
        return arxiv_id
    for key in ("external_id", "id", "paper_id", "uid", "url"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _to_external_paper(item: dict[str, Any]) -> ExternalPaper:
    doi = _extract_doi(item)
    arxiv_id = _extract_arxiv_id(item)
    published = (
        item.get("publish_at")
        or item.get("published_at")
        or item.get("published")
        or item.get("date")
    )
    year = _extract_year(item.get("year")) or _extract_year(published)

    return ExternalPaper(
        title=str(item.get("title") or "").strip(),
        authors=_extract_authors(item),
        year=year,
        abstract=str(item.get("abstract") or item.get("summary") or "").strip(),
        doi=doi,
        arxiv_id=arxiv_id,
        venue=(str(item.get("venue")) if item.get("venue") else None),
        url=(str(item.get("url") or item.get("link")) if (item.get("url") or item.get("link")) else None),
        citation_count=_extract_citation_count(item),
        source="deepxiv_arxiv",
        external_id=_external_id(item, doi, arxiv_id),
    )


def _deepxiv_failure_message(result: HttpJsonResult) -> str:
    if result.status_code is not None:
        return f"DeepXiv request failed: upstream service returned HTTP {result.status_code}."
    if result.error:
        return f"DeepXiv request failed: {result.error}."
    return "DeepXiv request failed."


def search_by_topic(topic: str, cfg: DeepXivConfig, *, limit: int = 20) -> list[ExternalPaper]:
    """Search topic candidates from DeepXiv."""
    if not cfg.enabled:
        raise RuntimeError("DeepXiv is disabled in config ([deepxiv].enabled=false).")

    token = cfg.api_token
    if not token:
        raise RuntimeError(
            "DeepXiv token is not configured. Set [deepxiv].api_token_env and the environment variable."
        )

    url = cfg.base_url.rstrip("/") + "/"
    params = {
        "type": "retrieve",
        "query": topic,
        "size": limit,
        "offset": 0,
        "search_mode": cfg.search_mode,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    result = http_post_json_result(
        url,
        params=params,
        timeout=cfg.timeout_seconds,
        headers=headers,
    )
    if result.status_code == 405:
        result = http_get_json_result(
            url,
            params=params,
            timeout=cfg.timeout_seconds,
            headers=headers,
        )

    payload = result.payload
    if payload is None:
        raise RuntimeError(_deepxiv_failure_message(result))

    results = _extract_results(payload)
    return [_to_external_paper(item) for item in results]
