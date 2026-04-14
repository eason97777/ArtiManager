"""Shared data models for the discovery layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExternalPaper:
    """A paper returned by an external discovery source."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    doi: str | None = None
    arxiv_id: str | None = None
    venue: str | None = None
    url: str | None = None
    citation_count: int | None = None
    source: str = ""  # "semantic_scholar" | "arxiv" | "deepxiv_arxiv"
    external_id: str = ""  # DOI or arXiv ID
