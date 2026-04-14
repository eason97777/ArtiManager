"""Dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from artimanager.web.deps import context, get_templates, open_db, parse_json_list

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    templates = get_templates(request)
    conn = open_db(request)
    try:
        counts = {
            "papers_total": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
            "papers_inbox": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE workflow_status = 'inbox'"
            ).fetchone()[0],
            "discovery_new": conn.execute(
                "SELECT COUNT(*) FROM discovery_results WHERE status = 'new'"
            ).fetchone()[0],
            "tracking_enabled": conn.execute(
                "SELECT COUNT(*) FROM tracking_rules WHERE enabled = 1"
            ).fetchone()[0],
            "analysis_total": conn.execute(
                "SELECT COUNT(*) FROM analysis_records"
            ).fetchone()[0],
        }
        recent_rows = conn.execute(
            "SELECT analysis_id, analysis_type, paper_ids, provider_id, created_at "
            "FROM analysis_records ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
        recent_analyses = [
            {
                "analysis_id": row[0],
                "analysis_type": row[1],
                "paper_ids": parse_json_list(row[2]),
                "provider_id": row[3],
                "created_at": row[4],
            }
            for row in recent_rows
        ]
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context(request, counts=counts, recent_analyses=recent_analyses),
    )
