"""Zotero data models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ZoteroItem:
    """A Zotero library item, normalised for internal use."""

    key: str
    item_type: str  # "journalArticle", "book", "conferencePaper", etc.
    title: str
    creators: list[dict]  # {firstName, lastName, creatorType} or {name}
    date: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    tags: list[str] = field(default_factory=list)
    extra: str | None = None
    url: str | None = None
    collections: list[str] = field(default_factory=list)
    date_added: str = ""
    date_modified: str = ""


_ARXIV_RE = re.compile(r"(?:arxiv:\s*)([\w./-]+)", re.IGNORECASE)


def _parse_extra(extra: str | None) -> str | None:
    """Extract arXiv ID from Zotero's extra field, if present."""
    if not extra:
        return None
    m = _ARXIV_RE.search(extra)
    return m.group(1) if m else None


def item_from_zotero_data(data: dict) -> ZoteroItem:
    """Convert a raw pyzotero item's 'data' dict into a ZoteroItem."""
    doi = data.get("DOI") or None
    extra = data.get("extra") or None
    arxiv_id = _parse_extra(extra)

    raw_tags = data.get("tags", [])
    tags = [t["tag"] if isinstance(t, dict) else t for t in raw_tags]

    return ZoteroItem(
        key=data.get("key", ""),
        item_type=data.get("itemType", ""),
        title=data.get("title", ""),
        creators=data.get("creators", []),
        date=data.get("date") or None,
        doi=doi,
        arxiv_id=arxiv_id,
        abstract=data.get("abstractNote") or None,
        tags=tags,
        extra=extra,
        url=data.get("url") or None,
        collections=data.get("collections", []),
        date_added=data.get("dateAdded", ""),
        date_modified=data.get("dateModified", ""),
    )
