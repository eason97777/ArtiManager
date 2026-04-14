"""Paper read routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from artimanager.analysis.manager import list_analyses
from artimanager.notes.manager import get_note
from artimanager.relationships.manager import get_relationships
from artimanager.validation.manager import get_validations
from artimanager.web.deps import context, get_templates, open_db, parse_json_list

router = APIRouter()


def _note_preview(path: Path) -> str | None:
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    normalized = " ".join(line.strip() for line in text.splitlines()).strip()
    if not normalized:
        return None
    if len(normalized) <= 280:
        return normalized
    return normalized[:280].rstrip() + "..."


def _paper_detail_payload(conn, paper_id: str) -> dict:
    paper_row = conn.execute(
        """
        SELECT paper_id, title, authors, year, venue, abstract, doi, arxiv_id,
               workflow_status, reading_state, research_state, created_at, updated_at
        FROM papers WHERE paper_id = ?
        """,
        (paper_id,),
    ).fetchone()
    if paper_row is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")

    file_rows = conn.execute(
        """
        SELECT file_id, absolute_path, filename, filesize, mime_type,
               import_status, created_at
        FROM file_assets
        WHERE paper_id = ?
        ORDER BY created_at DESC
        """,
        (paper_id,),
    ).fetchall()
    zotero_row = conn.execute(
        """
        SELECT zotero_library_id, zotero_item_key, attachment_mode, last_synced_at
        FROM zotero_links WHERE paper_id = ?
        """,
        (paper_id,),
    ).fetchone()

    paper = {
        "paper_id": paper_row[0],
        "title": paper_row[1] or "(untitled)",
        "authors": parse_json_list(paper_row[2]),
        "year": paper_row[3],
        "venue": paper_row[4],
        "abstract": paper_row[5],
        "doi": paper_row[6],
        "arxiv_id": paper_row[7],
        "workflow_status": paper_row[8],
        "reading_state": paper_row[9],
        "research_state": paper_row[10],
        "created_at": paper_row[11],
        "updated_at": paper_row[12],
    }
    files = [
        {
            "file_id": row[0],
            "absolute_path": row[1],
            "filename": row[2],
            "filesize": row[3],
            "mime_type": row[4],
            "import_status": row[5],
            "created_at": row[6],
        }
        for row in file_rows
    ]

    note = None
    note_record = get_note(conn, paper_id)
    if note_record is not None:
        note_path = Path(note_record.location)
        note_exists = note_path.exists()
        note = {
            "note_id": note_record.note_id,
            "note_type": note_record.note_type,
            "location": note_record.location,
            "title": note_record.title,
            "updated_at": note_record.updated_at,
            "exists": note_exists,
            "preview": _note_preview(note_path) if note_exists else None,
        }

    validations = get_validations(conn, paper_id)
    analyses = list_analyses(conn, paper_id=paper_id, limit=100)
    relationships = get_relationships(conn, paper_id, direction="both")

    relation_rows = [
        {
            "relationship_id": item.relationship_id,
            "source_paper_id": item.source_paper_id,
            "target_paper_id": item.target_paper_id,
            "relationship_type": item.relationship_type,
            "status": item.status,
            "evidence_type": item.evidence_type,
            "evidence_text": item.evidence_text,
            "confidence": item.confidence,
            "created_at": item.created_at,
        }
        for item in relationships
    ]
    confirmed_relationships = [r for r in relation_rows if r["status"] == "confirmed"]
    suggested_relationships = [r for r in relation_rows if r["status"] == "suggested"]
    other_relationships = [
        r for r in relation_rows if r["status"] not in {"confirmed", "suggested"}
    ]

    zotero_link = None
    if zotero_row is not None:
        zotero_link = {
            "zotero_library_id": zotero_row[0],
            "zotero_item_key": zotero_row[1],
            "attachment_mode": zotero_row[2],
            "last_synced_at": zotero_row[3],
        }

    return {
        "paper": paper,
        "files": files,
        "note": note,
        "validations": validations,
        "zotero_link": zotero_link,
        "confirmed_relationships": confirmed_relationships,
        "suggested_relationships": suggested_relationships,
        "other_relationships": other_relationships,
        "analyses": analyses,
    }


def render_paper_detail_page(
    request: Request,
    paper_id: str,
    *,
    status_code: int = 200,
    error_message: str | None = None,
) -> HTMLResponse:
    templates = get_templates(request)
    conn = open_db(request)
    try:
        payload = _paper_detail_payload(conn, paper_id)
    finally:
        conn.close()

    data = context(
        request,
        paper_id=paper_id,
        **payload,
    )
    if error_message is not None:
        data["error_message"] = error_message
    return templates.TemplateResponse(
        request,
        "paper_detail.html",
        data,
        status_code=status_code,
    )


@router.get("/papers/inbox", response_class=HTMLResponse)
def papers_inbox(request: Request):
    templates = get_templates(request)
    conn = open_db(request)
    try:
        rows = conn.execute(
            """
            SELECT p.paper_id, p.title, p.authors, p.year, p.doi, p.arxiv_id,
                   p.workflow_status, COUNT(f.file_id) AS file_count
            FROM papers p
            LEFT JOIN file_assets f ON f.paper_id = p.paper_id
            WHERE p.workflow_status = 'inbox'
            GROUP BY p.paper_id
            ORDER BY p.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    papers = [
        {
            "paper_id": row[0],
            "title": row[1] or "(untitled)",
            "authors": parse_json_list(row[2]),
            "year": row[3],
            "doi": row[4],
            "arxiv_id": row[5],
            "workflow_status": row[6],
            "file_count": row[7],
        }
        for row in rows
    ]
    return templates.TemplateResponse(
        request,
        "inbox.html",
        context(request, papers=papers),
    )


@router.get("/papers/{paper_id}", response_class=HTMLResponse)
def paper_detail(request: Request, paper_id: str):
    return render_paper_detail_page(request, paper_id)
