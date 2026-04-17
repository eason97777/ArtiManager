"""Search routes."""

from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from artimanager.search.query import (
    SearchFilters,
    SearchResult,
    search_all,
    search_fulltext,
    search_papers,
)
from artimanager.web.deps import context, get_templates, open_db, parse_csv

router = APIRouter()


def _parse_optional_int(
    raw: str | None,
    *,
    field_name: str,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> tuple[int | None, str | None]:
    if raw is None or not raw.strip():
        return default, None
    try:
        value = int(raw)
    except ValueError:
        return None, f"{field_name} must be an integer."
    if minimum is not None and value < minimum:
        return None, f"{field_name} must be at least {minimum}."
    if maximum is not None and value > maximum:
        return None, f"{field_name} must be at most {maximum}."
    return value, None


def _has_browse_filters(filters: SearchFilters) -> bool:
    return any([
        filters.workflow_status,
        filters.reading_state,
        filters.year_min is not None,
        filters.year_max is not None,
    ])


def _browse_papers(conn, filters: SearchFilters, limit: int) -> list[SearchResult]:
    clauses: list[str] = []
    params: list = []
    if filters.workflow_status:
        placeholders = ", ".join("?" for _ in filters.workflow_status)
        clauses.append(f"workflow_status IN ({placeholders})")
        params.extend(filters.workflow_status)
    if filters.reading_state:
        placeholders = ", ".join("?" for _ in filters.reading_state)
        clauses.append(f"reading_state IN ({placeholders})")
        params.extend(filters.reading_state)
    if filters.year_min is not None:
        clauses.append("year >= ?")
        params.append(filters.year_min)
    if filters.year_max is not None:
        clauses.append("year <= ?")
        params.append(filters.year_max)

    sql = "SELECT paper_id, title, authors, year FROM papers"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [
        SearchResult(
            paper_id=row[0],
            title=row[1] or "",
            authors=json.loads(row[2]) if row[2] else [],
            year=row[3],
            match_source="browse",
            snippet="",
            score=0.0,
        )
        for row in rows
    ]


@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str = Query(default=""),
    source: str = Query(default="all", pattern="^(metadata|fulltext|all)$"),
    status: str | None = Query(default=None),
    reading: str | None = Query(default=None),
    year_min: str | None = Query(default=None),
    year_max: str | None = Query(default=None),
    limit: str | None = Query(default="20"),
):
    templates = get_templates(request)
    parsed_year_min, year_min_error = _parse_optional_int(
        year_min,
        field_name="Year Min",
    )
    parsed_year_max, year_max_error = _parse_optional_int(
        year_max,
        field_name="Year Max",
    )
    parsed_limit, limit_error = _parse_optional_int(
        limit,
        field_name="Limit",
        default=20,
        minimum=1,
        maximum=200,
    )
    parse_errors = [
        error
        for error in (year_min_error, year_max_error, limit_error)
        if error is not None
    ]
    effective_limit = parsed_limit or 20

    filters = SearchFilters(
        workflow_status=parse_csv(status),
        reading_state=parse_csv(reading),
        year_min=parsed_year_min,
        year_max=parsed_year_max,
    )
    rows = []
    query_error = "; ".join(parse_errors) if parse_errors else None
    state_map: dict[str, dict[str, str]] = {}

    if not query_error and (q.strip() or _has_browse_filters(filters)):
        conn = open_db(request)
        try:
            if not q.strip():
                rows = _browse_papers(conn, filters, effective_limit)
            elif source == "metadata":
                rows = search_papers(conn, q, filters)[:effective_limit]
            elif source == "fulltext":
                rows = search_fulltext(conn, q, filters)[:effective_limit]
            else:
                rows = search_all(conn, q, filters, limit=effective_limit)
            paper_ids = sorted({item.paper_id for item in rows})
            if paper_ids:
                placeholders = ", ".join("?" for _ in paper_ids)
                state_rows = conn.execute(
                    f"""
                    SELECT paper_id, workflow_status, reading_state, research_state
                    FROM papers
                    WHERE paper_id IN ({placeholders})
                    """,
                    paper_ids,
                ).fetchall()
                state_map = {
                    row[0]: {
                        "workflow_status": row[1],
                        "reading_state": row[2],
                        "research_state": row[3],
                    }
                    for row in state_rows
                }
        except ValueError as exc:
            query_error = str(exc)
        finally:
            conn.close()

    grouped: dict[str, list] = defaultdict(list)
    for item in rows:
        grouped[item.match_source].append(item)

    return templates.TemplateResponse(
        request,
        "search.html",
        context(
            request,
            q=q,
            source=source,
            status=status or "",
            reading=reading or "",
            year_min=year_min or "",
            year_max=year_max or "",
            limit=limit if limit is not None else "",
            grouped_results=dict(grouped),
            state_map=state_map,
            total_results=len(rows),
            query_error=query_error,
        ),
    )
