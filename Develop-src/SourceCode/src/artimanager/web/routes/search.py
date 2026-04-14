"""Search routes."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from artimanager.search.query import SearchFilters, search_all, search_fulltext, search_papers
from artimanager.web.deps import context, get_templates, open_db, parse_csv

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str = Query(default=""),
    source: str = Query(default="all", pattern="^(metadata|fulltext|all)$"),
    status: str | None = Query(default=None),
    reading: str | None = Query(default=None),
    year_min: int | None = Query(default=None),
    year_max: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
):
    templates = get_templates(request)

    filters = SearchFilters(
        workflow_status=parse_csv(status),
        reading_state=parse_csv(reading),
        year_min=year_min,
        year_max=year_max,
    )
    rows = []
    query_error = None

    if q.strip():
        conn = open_db(request)
        try:
            if source == "metadata":
                rows = search_papers(conn, q, filters)[:limit]
            elif source == "fulltext":
                rows = search_fulltext(conn, q, filters)[:limit]
            else:
                rows = search_all(conn, q, filters, limit=limit)
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
            year_min=year_min,
            year_max=year_max,
            limit=limit,
            grouped_results=dict(grouped),
            total_results=len(rows),
            query_error=query_error,
        ),
    )
