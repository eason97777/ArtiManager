"""Search query layer — retrieve papers via FTS5 indexes.

Provides metadata search, full-text search, and a combined search_all
that groups results by canonical paper record.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass
class SearchFilters:
    """Optional filters applied to search results."""

    workflow_status: list[str] | None = None
    reading_state: list[str] | None = None
    research_state: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None
    tags: list[str] | None = None


@dataclass
class SearchResult:
    """A single search hit."""

    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    match_source: str  # "metadata" | "fulltext" | "note"
    snippet: str
    score: float


def _build_filter_clause(
    filters: SearchFilters | None,
    paper_alias: str = "p",
) -> tuple[str, list]:
    """Build SQL WHERE fragments and params from filters.

    Returns (clause_string, params_list). clause_string may be empty.
    """
    if filters is None:
        return "", []

    clauses: list[str] = []
    params: list = []

    if filters.workflow_status:
        placeholders = ", ".join("?" for _ in filters.workflow_status)
        clauses.append(f"{paper_alias}.workflow_status IN ({placeholders})")
        params.extend(filters.workflow_status)

    if filters.reading_state:
        placeholders = ", ".join("?" for _ in filters.reading_state)
        clauses.append(f"{paper_alias}.reading_state IN ({placeholders})")
        params.extend(filters.reading_state)

    if filters.research_state:
        placeholders = ", ".join("?" for _ in filters.research_state)
        clauses.append(f"{paper_alias}.research_state IN ({placeholders})")
        params.extend(filters.research_state)

    if filters.year_min is not None:
        clauses.append(f"{paper_alias}.year >= ?")
        params.append(filters.year_min)

    if filters.year_max is not None:
        clauses.append(f"{paper_alias}.year <= ?")
        params.append(filters.year_max)

    if filters.tags:
        tags_normalized = [
            " ".join(tag.split()).lower()
            for tag in filters.tags
            if tag and " ".join(tag.split())
        ]
        if tags_normalized:
            placeholders = ", ".join("?" for _ in tags_normalized)
            clauses.append(
                f"""{paper_alias}.paper_id IN (
                    SELECT pt.paper_id FROM paper_tags pt
                    JOIN tags t ON t.tag_id = pt.tag_id
                    WHERE lower(t.name) IN ({placeholders})
                )"""
            )
            params.extend(tags_normalized)
    clause = " AND ".join(clauses)
    return clause, params


def _parse_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [raw]


def search_papers(
    conn: sqlite3.Connection,
    query: str,
    filters: SearchFilters | None = None,
) -> list[SearchResult]:
    """Search paper metadata (title, authors, abstract) via FTS5."""
    filter_clause, filter_params = _build_filter_clause(filters)

    sql = """
        SELECT p.paper_id, p.title, p.authors, p.year,
               snippet(papers_fts, 1, '>>>', '<<<', '...', 32) AS snip,
               rank
        FROM papers_fts
        JOIN papers p ON p.paper_id = papers_fts.paper_id
        WHERE papers_fts MATCH ?
    """
    params: list = [query]

    if filter_clause:
        sql += f" AND {filter_clause}"
        params.extend(filter_params)

    sql += " ORDER BY rank"

    results: list[SearchResult] = []
    for row in conn.execute(sql, params).fetchall():
        results.append(SearchResult(
            paper_id=row[0],
            title=row[1] or "",
            authors=_parse_authors(row[2]),
            year=row[3],
            match_source="metadata",
            snippet=row[4] or "",
            score=-row[5],  # FTS5 rank is negative; negate for intuitive ordering
        ))
    return results


def search_fulltext(
    conn: sqlite3.Connection,
    query: str,
    filters: SearchFilters | None = None,
) -> list[SearchResult]:
    """Search full-text content via FTS5."""
    filter_clause, filter_params = _build_filter_clause(filters)

    sql = """
        SELECT p.paper_id, p.title, p.authors, p.year,
               snippet(fulltext_fts, 1, '>>>', '<<<', '...', 32) AS snip,
               rank
        FROM fulltext_fts
        JOIN papers p ON p.paper_id = fulltext_fts.paper_id
        WHERE fulltext_fts MATCH ?
    """
    params: list = [query]

    if filter_clause:
        sql += f" AND {filter_clause}"
        params.extend(filter_params)

    sql += " ORDER BY rank"

    results: list[SearchResult] = []
    for row in conn.execute(sql, params).fetchall():
        results.append(SearchResult(
            paper_id=row[0],
            title=row[1] or "",
            authors=_parse_authors(row[2]),
            year=row[3],
            match_source="fulltext",
            snippet=row[4] or "",
            score=-row[5],
        ))
    return results


def search_notes(
    conn: sqlite3.Connection,
    query: str,
    filters: SearchFilters | None = None,
) -> list[SearchResult]:
    """Search markdown note content via FTS5."""
    filter_clause, filter_params = _build_filter_clause(filters)

    sql = """
        SELECT p.paper_id, p.title, p.authors, p.year,
               snippet(notes_fts, 2, '>>>', '<<<', '...', 32) AS snip,
               rank
        FROM notes_fts
        JOIN papers p ON p.paper_id = notes_fts.paper_id
        WHERE notes_fts MATCH ?
    """
    params: list = [query]

    if filter_clause:
        sql += f" AND {filter_clause}"
        params.extend(filter_params)

    sql += " ORDER BY rank"

    results: list[SearchResult] = []
    for row in conn.execute(sql, params).fetchall():
        results.append(SearchResult(
            paper_id=row[0],
            title=row[1] or "",
            authors=_parse_authors(row[2]),
            year=row[3],
            match_source="note",
            snippet=row[4] or "",
            score=-row[5],
        ))
    return results


def search_all(
    conn: sqlite3.Connection,
    query: str,
    filters: SearchFilters | None = None,
    *,
    limit: int = 20,
) -> list[SearchResult]:
    """Combined search across metadata, fulltext, and notes.

    Groups by paper_id, keeping the highest-scoring match per paper.
    """
    all_results = (
        search_papers(conn, query, filters)
        + search_fulltext(conn, query, filters)
        + search_notes(conn, query, filters)
    )

    # Group by paper_id — keep best score
    best: dict[str, SearchResult] = {}
    for r in all_results:
        if r.paper_id not in best or r.score > best[r.paper_id].score:
            best[r.paper_id] = r

    ranked = sorted(best.values(), key=lambda r: r.score, reverse=True)
    return ranked[:limit]
