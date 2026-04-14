"""Analysis read routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from artimanager.analysis.manager import get_analysis, list_analyses
from artimanager.web.deps import context, get_templates, open_db

router = APIRouter()


@router.get("/analyses", response_class=HTMLResponse)
def analysis_list_page(
    request: Request,
    paper_id: str | None = Query(default=None),
    analysis_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    templates = get_templates(request)
    conn = open_db(request)
    try:
        records = list_analyses(
            conn,
            paper_id=paper_id,
            analysis_type=analysis_type,
            limit=limit,
        )
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "analysis_list.html",
        context(
            request,
            records=records,
            paper_id_filter=paper_id or "",
            analysis_type_filter=analysis_type or "",
            limit=limit,
        ),
    )


@router.get("/analyses/{analysis_id}", response_class=HTMLResponse)
def analysis_detail_page(request: Request, analysis_id: str):
    templates = get_templates(request)
    conn = open_db(request)
    try:
        record = get_analysis(conn, analysis_id)
    finally:
        conn.close()
    if record is None:
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")

    artifact_text = None
    artifact_error = None
    if record.content_location:
        path = Path(record.content_location)
        if path.exists():
            artifact_text = path.read_text()
        else:
            artifact_error = f"Artifact not found at: {record.content_location}"

    return templates.TemplateResponse(
        request,
        "analysis_detail.html",
        context(
            request,
            record=record,
            artifact_text=artifact_text,
            artifact_error=artifact_error,
        ),
    )
