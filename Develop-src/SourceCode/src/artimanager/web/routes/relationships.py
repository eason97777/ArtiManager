"""Relationship review routes."""

from __future__ import annotations

from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from artimanager.relationships.manager import (
    get_relationship,
    list_relationships,
    update_relationship_status,
)
from artimanager.web.deps import context, get_templates, open_db
from artimanager.web.routes.papers import render_paper_detail_page

router = APIRouter()


def _normalize_redirect_target(redirect_to: str) -> tuple[str, list[tuple[str, str]]]:
    parsed = urlparse(redirect_to)
    redirect_path = parsed.path or "/relationships/review"
    if not redirect_path.startswith("/"):
        redirect_path = "/relationships/review"
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    return redirect_path, query_pairs


def _filters_from_query_pairs(
    query_pairs: list[tuple[str, str]],
) -> tuple[str | None, str | None, int]:
    qs = parse_qs(urlencode(query_pairs), keep_blank_values=True)
    paper_id = (qs.get("paper_id", [""])[0] or "").strip() or None
    status = (qs.get("status", [""])[0] or "").strip() or None
    if status == "all":
        status = None
    raw_limit = (qs.get("limit", [""])[0] or "").strip()
    limit = 120
    if raw_limit:
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = 120
    limit = max(1, min(500, limit))
    return paper_id, status, limit


def _load_relationship_rows(
    request: Request,
    *,
    paper_id: str | None,
    status: str | None,
    limit: int,
):
    conn = open_db(request)
    try:
        records = list_relationships(conn, paper_id=paper_id, status=status, limit=limit)
        paper_ids: set[str] = set()
        for item in records:
            paper_ids.add(item.source_paper_id)
            paper_ids.add(item.target_paper_id)
        title_map: dict[str, str] = {}
        if paper_ids:
            placeholders = ", ".join("?" for _ in paper_ids)
            rows = conn.execute(
                f"SELECT paper_id, title FROM papers WHERE paper_id IN ({placeholders})",
                list(paper_ids),
            ).fetchall()
            title_map = {row[0]: (row[1] or "(untitled)") for row in rows}
    finally:
        conn.close()

    return [
        {
            "relationship_id": item.relationship_id,
            "source_paper_id": item.source_paper_id,
            "target_paper_id": item.target_paper_id,
            "source_title": title_map.get(item.source_paper_id, "(unknown paper)"),
            "target_title": title_map.get(item.target_paper_id, "(unknown paper)"),
            "relationship_type": item.relationship_type,
            "status": item.status,
            "evidence_type": item.evidence_type,
            "evidence_text": item.evidence_text,
            "confidence": item.confidence,
            "created_at": item.created_at,
        }
        for item in records
    ]


def _render_relationship_queue(
    request: Request,
    *,
    paper_id: str | None,
    status: str | None,
    limit: int,
    status_code: int = 200,
    error_message: str | None = None,
) -> HTMLResponse:
    templates = get_templates(request)
    rows = _load_relationship_rows(
        request,
        paper_id=paper_id,
        status=status,
        limit=limit,
    )
    data = context(
        request,
        rows=rows,
        paper_id_filter=paper_id or "",
        status_filter=status or "all",
        limit=limit,
    )
    if error_message is not None:
        data["error_message"] = error_message
    return templates.TemplateResponse(
        request,
        "relationships_review.html",
        data,
        status_code=status_code,
    )


@router.get("/relationships/review", response_class=HTMLResponse)
def relationship_review_queue(
    request: Request,
    paper_id: str | None = Query(default=None),
    status: str = Query(default="suggested"),
    limit: int = Query(default=120, ge=1, le=500),
):
    status_filter = None if status in {"", "all"} else status
    return _render_relationship_queue(
        request,
        paper_id=paper_id,
        status=status_filter,
        limit=limit,
    )


@router.post("/relationships/{relationship_id}/review", response_class=HTMLResponse)
def relationship_review_post(
    request: Request,
    relationship_id: str,
    action: str = Form(...),
    redirect_to: str = Form(default="/relationships/review"),
):
    if action not in {"confirm", "reject"}:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")
    new_status = "confirmed" if action == "confirm" else "rejected"

    redirect_path, redirect_query = _normalize_redirect_target(redirect_to)
    filter_paper_id, filter_status, filter_limit = _filters_from_query_pairs(redirect_query)

    conn = open_db(request)
    try:
        rel = get_relationship(conn, relationship_id)
        if rel is None:
            raise HTTPException(status_code=404, detail=f"Relationship {relationship_id!r} not found")

        update_relationship_status(conn, relationship_id, new_status)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        if redirect_path.startswith("/papers/"):
            paper_id = redirect_path.strip("/").split("/")[1]
            return render_paper_detail_page(
                request,
                paper_id,
                status_code=400,
                error_message=message,
            )
        return _render_relationship_queue(
            request,
            paper_id=filter_paper_id,
            status=filter_status,
            limit=filter_limit,
            status_code=400,
            error_message=message,
        )
    finally:
        conn.close()

    message = f"Relationship {relationship_id} {action}ed."
    next_query = [(k, v) for (k, v) in redirect_query if k not in {"ok", "error"}]
    next_query.append(("ok", message))
    redirect_url = redirect_path
    if next_query:
        redirect_url += f"?{urlencode(next_query)}"
    return RedirectResponse(url=redirect_url, status_code=303)
