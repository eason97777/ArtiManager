"""arXiv API adapter.

Uses the arXiv Atom feed API (http://export.arxiv.org/api/query).
No API key required.  Returns XML (Atom), not JSON.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

from artimanager.discovery._http import http_get_raw
from artimanager.discovery._models import ExternalPaper

logger = logging.getLogger(__name__)

_ARXIV_API = "https://export.arxiv.org/api/query"
_ARXIV_ID_RE = re.compile(r"arxiv\.org/abs/(\d+\.\d+(?:v\d+)?)")
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


def _extract_arxiv_id(entry_id: str) -> str | None:
    m = _ARXIV_ID_RE.search(entry_id)
    return m.group(1) if m else None


def _extract_year(published: str) -> int | None:
    m = _YEAR_RE.search(published)
    return int(m.group(1)) if m else None


def _parse_authors(entry: ET.Element) -> list[str]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    return [
        el.text or ""
        for el in entry.findall("atom:author/atom:name", ns)
        if el.text
    ]


def _parse_atom_entry(entry: ET.Element) -> ExternalPaper:
    """Parse one Atom <entry> into ExternalPaper."""
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    entry_id = (entry.findtext("atom:id", namespaces=ns) or "").strip()
    title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
    # Collapse whitespace in title (arXiv API returns multi-line titles)
    title = re.sub(r"\s+", " ", title)
    abstract = (entry.findtext("atom:summary", namespaces=ns) or "").strip()
    published = (entry.findtext("atom:published", namespaces=ns) or "").strip()
    year = _extract_year(published)
    arxiv_id = _extract_arxiv_id(entry_id)
    authors = _parse_authors(entry)

    return ExternalPaper(
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        arxiv_id=arxiv_id,
        source="arxiv",
        external_id=arxiv_id or "",
        url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
    )


def search(query: str, max_results: int = 20) -> list[ExternalPaper]:
    """Search arXiv using an explicit arXiv query expression."""
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
    }
    text = http_get_raw(_ARXIV_API, params=params)
    if text is None:
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        logger.warning("Failed to parse arXiv Atom XML")
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    return [_parse_atom_entry(e) for e in entries]


def search_by_topic(topic: str, max_results: int = 20) -> list[ExternalPaper]:
    """Search arXiv by topic/keyword."""
    return search(f"all:{topic}", max_results=max_results)


def search_by_author(author: str, max_results: int = 20) -> list[ExternalPaper]:
    """Search arXiv by author name."""
    escaped = author.replace('"', "")
    return search(f'au:"{escaped}"', max_results=max_results)


def search_by_category(category: str, max_results: int = 20) -> list[ExternalPaper]:
    """Search arXiv by category expression (e.g. cs.AI)."""
    return search(f"cat:{category}", max_results=max_results)
