"""Discovery inbox read/write routes."""

from __future__ import annotations

from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from artimanager.discovery.review import (
    DISCOVERY_REVIEW_ACTIONS,
    review_discovery_result,
)
from artimanager.web.deps import (
    context,
    get_app_config,
    get_templates,
    open_db,
    parse_json_list,
)
from artimanager.web.view_models import (
    clean_relevance_context_for_display,
    compact_author_list,
    load_provenance_views,
)

router = APIRouter()


def _normalize_redirect_target(redirect_to: str) -> tuple[str, list[tuple[str, str]]]:
    parsed = urlparse(redirect_to)
    redirect_path = parsed.path or "/discovery"
    if not redirect_path.startswith("/"):
        redirect_path = "/discovery"
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    return redirect_path, query_pairs


def _filters_from_query_pairs(query_pairs: list[tuple[str, str]]) -> tuple[str | None, str | None, str | None, int]:
    qs = parse_qs(urlencode(query_pairs), keep_blank_values=True)
    status = (qs.get("status", [""])[0] or "").strip() or None
    trigger_type = (qs.get("trigger_type", [""])[0] or "").strip() or None
    trigger_ref = (qs.get("trigger_ref", [""])[0] or "").strip() or None
    raw_limit = (qs.get("limit", [""])[0] or "").strip()
    limit = 80
    if raw_limit:
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = 80
    limit = max(1, min(500, limit))
    return status, trigger_type, trigger_ref, limit


def _load_discovery_rows(
    request: Request,
    *,
    status: str | None,
    trigger_type: str | None,
    trigger_ref: str | None,
    limit: int,
):
    conn = open_db(request)
    try:
        sql = (
            "SELECT discovery_result_id, title, authors, source, external_id, published_at, "
            "relevance_score, relevance_context, status, review_action, trigger_type, trigger_ref "
            "FROM discovery_results"
        )
        clauses: list[str] = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if trigger_type:
            clauses.append("trigger_type = ?")
            params.append(trigger_type)
        if trigger_ref:
            clauses.append("trigger_ref = ?")
            params.append(trigger_ref)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        provenance_by_result = load_provenance_views(conn, [row[0] for row in rows])
    finally:
        conn.close()

    return [
        {
            "discovery_result_id": row[0],
            "title": row[1] or "(untitled)",
            "authors": parse_json_list(row[2]),
            "author_line": compact_author_list(parse_json_list(row[2])),
            "source": row[3],
            "external_id": row[4],
            "published_at": row[5],
            "relevance_score": row[6],
            "relevance_context": clean_relevance_context_for_display(
                row[7],
                relevance_score=row[6],
            ),
            "status": row[8],
            "review_action": row[9],
            "trigger_type": row[10],
            "trigger_ref": row[11],
            "provenance": provenance_by_result.get(row[0], []),
        }
        for row in rows
    ]


@router.get("/discovery", response_class=HTMLResponse)
def discovery_inbox_page(
    request: Request,
    status: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    trigger_ref: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=500),
):
    templates = get_templates(request)
    rows = _load_discovery_rows(
        request,
        status=status,
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
        limit=limit,
    )
    return templates.TemplateResponse(
        request,
        "discovery_inbox.html",
        context(
            request,
            rows=rows,
            status_filter=status or "",
            trigger_type_filter=trigger_type or "",
            trigger_ref_filter=trigger_ref or "",
            limit=limit,
            review_actions=DISCOVERY_REVIEW_ACTIONS,
        ),
    )


@router.post("/discovery/{result_id}/review", response_class=HTMLResponse)
def discovery_review_post(
    request: Request,
    result_id: str,
    action: str = Form(...),
    link_to_paper: str | None = Form(default=None),
    author_name: str | None = Form(default=None),
    redirect_to: str = Form(default="/discovery"),
):
    templates = get_templates(request)
    cfg = get_app_config(request)

    redirect_path, redirect_query = _normalize_redirect_target(redirect_to)
    status_filter, trigger_type_filter, trigger_ref_filter, limit_filter = _filters_from_query_pairs(
        redirect_query
    )

    conn = open_db(request)
    try:
        outcome = review_discovery_result(
            conn,
            cfg,
            result_id=result_id,
            action=action,
            link_to_paper=link_to_paper,
            author_name=author_name,
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        message = str(exc)
        if message.startswith("Discovery result ") and message.endswith(" not found."):
            raise HTTPException(status_code=404, detail=message) from exc
        rows = _load_discovery_rows(
            request,
            status=status_filter,
            trigger_type=trigger_type_filter,
            trigger_ref=trigger_ref_filter,
            limit=limit_filter,
        )
        return templates.TemplateResponse(
            request,
            "discovery_inbox.html",
            context(
                request,
                rows=rows,
                status_filter=status_filter or "",
                trigger_type_filter=trigger_type_filter or "",
                trigger_ref_filter=trigger_ref_filter or "",
                limit=limit_filter,
                review_actions=DISCOVERY_REVIEW_ACTIONS,
                error_message=message,
            ),
            status_code=400,
        )
    finally:
        conn.close()

    next_query = [(k, v) for (k, v) in redirect_query if k != "ok"]
    next_query.append(("ok", outcome.message))
    redirect_url = redirect_path
    if next_query:
        redirect_url += f"?{urlencode(next_query)}"
    return RedirectResponse(url=redirect_url, status_code=303)
