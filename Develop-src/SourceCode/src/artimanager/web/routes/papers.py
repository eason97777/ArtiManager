"""Paper read routes."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from artimanager.analysis.manager import list_analyses
from artimanager.notes.manager import get_note, init_note_from_template
from artimanager.papers.manager import (
    READING_STATE_VALUES,
    RESEARCH_STATE_VALUES,
    WORKFLOW_STATUS_VALUES,
    update_paper_metadata,
    update_paper_state,
)
from artimanager.relationships.manager import get_relationships
from artimanager.search.indexer import index_paper
from artimanager.tags.manager import (
    add_tag_to_paper,
    list_tags_for_paper,
    remove_tag_from_paper,
)
from artimanager.validation.manager import create_validation, get_validations
from artimanager.web.deps import (
    context,
    get_app_config,
    get_templates,
    open_db,
    parse_json_list,
)

router = APIRouter()


class LocalOpenError(RuntimeError):
    """Raised when a registered local file cannot be handed off to the OS."""


def _local_open_command(path: Path) -> list[str] | None:
    if sys.platform == "darwin":
        return ["open", str(path)]
    if sys.platform.startswith("linux"):
        return ["xdg-open", str(path)]
    return None


def _local_open_supported() -> bool:
    return _local_open_command(Path(".")) is not None or (
        os.name == "nt" and hasattr(os, "startfile")
    )


def _open_local_file(path: Path) -> None:
    if os.name == "nt" and hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    command = _local_open_command(path)
    if command is None:
        raise LocalOpenError(
            "Local file opening is not supported on this platform. Copy the path and open it manually."
        )
    try:
        subprocess.run(command, check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LocalOpenError(
            f"Could not open local file. Copy the path and open it manually: {exc}"
        ) from exc


def _safe_redirect_target(raw: str | None, fallback: str) -> str:
    if not raw:
        return fallback
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return fallback
    target = parsed.path
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if query:
        target += f"?{urlencode(query)}"
    return target


def _redirect_with_message(target: str, *, ok: str | None = None) -> RedirectResponse:
    parsed = urlparse(target)
    query = [(k, v) for (k, v) in parse_qsl(parsed.query, keep_blank_values=True) if k != "ok"]
    if ok:
        query.append(("ok", ok))
    url = parsed.path or "/"
    if query:
        url += f"?{urlencode(query)}"
    return RedirectResponse(url=url, status_code=303)


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
    tags = list_tags_for_paper(conn, paper_id)
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
        "tags": tags,
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
    if data.get("zotero_link") is not None:
        data["zotero_link"]["zotero_library_type"] = get_app_config(request).zotero.library_type
    data["local_open_supported"] = _local_open_supported()
    data["workflow_status_values"] = WORKFLOW_STATUS_VALUES
    data["reading_state_values"] = READING_STATE_VALUES
    data["research_state_values"] = RESEARCH_STATE_VALUES
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
                   p.workflow_status, p.reading_state, p.research_state,
                   COUNT(f.file_id) AS file_count
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
            "reading_state": row[7],
            "research_state": row[8],
            "file_count": row[9],
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


@router.post("/papers/{paper_id}/state", response_class=HTMLResponse)
def paper_state_update(
    request: Request,
    paper_id: str,
    workflow_status: str | None = Form(default=None),
    reading_state: str | None = Form(default=None),
    research_state: str | None = Form(default=None),
    redirect_to: str = Form(default=""),
):
    redirect_target = _safe_redirect_target(redirect_to, f"/papers/{paper_id}")
    conn = open_db(request)
    try:
        update_paper_state(
            conn,
            paper_id,
            workflow_status=workflow_status or None,
            reading_state=reading_state or None,
            research_state=research_state or None,
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        message = str(exc)
        if message.startswith("Paper not found:"):
            raise HTTPException(status_code=404, detail=message) from exc
        return render_paper_detail_page(request, paper_id, status_code=400, error_message=message)
    finally:
        conn.close()

    return _redirect_with_message(redirect_target, ok="Paper state updated.")


@router.post("/papers/{paper_id}/metadata", response_class=HTMLResponse)
def paper_metadata_update(
    request: Request,
    paper_id: str,
    title: str = Form(default=""),
    authors: str = Form(default=""),
    year: str = Form(default=""),
    doi: str = Form(default=""),
    arxiv_id: str = Form(default=""),
    abstract: str = Form(default=""),
):
    conn = open_db(request)
    try:
        update_paper_metadata(
            conn,
            paper_id,
            title=title,
            authors=authors,
            year=year,
            doi=doi,
            arxiv_id=arxiv_id,
            abstract=abstract,
        )
        index_paper(conn, paper_id)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        message = str(exc)
        if message.startswith("Paper not found:"):
            raise HTTPException(status_code=404, detail=message) from exc
        return render_paper_detail_page(request, paper_id, status_code=400, error_message=message)
    finally:
        conn.close()

    return _redirect_with_message(f"/papers/{paper_id}", ok="Paper metadata updated.")


@router.post("/papers/{paper_id}/tags", response_class=HTMLResponse)
def paper_tag_add(
    request: Request,
    paper_id: str,
    tag_name: str = Form(...),
    tag_type: str | None = Form(default=None),
):
    conn = open_db(request)
    try:
        tag = add_tag_to_paper(conn, paper_id, tag_name, tag_type=tag_type)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        message = str(exc)
        if message.startswith("Paper not found:"):
            raise HTTPException(status_code=404, detail=message) from exc
        return render_paper_detail_page(request, paper_id, status_code=400, error_message=message)
    finally:
        conn.close()

    return _redirect_with_message(f"/papers/{paper_id}", ok=f"Tag added: {tag.name}")


@router.post("/papers/{paper_id}/tags/remove", response_class=HTMLResponse)
def paper_tag_remove(
    request: Request,
    paper_id: str,
    tag_name: str = Form(...),
):
    conn = open_db(request)
    try:
        paper_row = conn.execute(
            "SELECT 1 FROM papers WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()
        if paper_row is None:
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id}")
        removed = remove_tag_from_paper(conn, paper_id, tag_name)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return render_paper_detail_page(request, paper_id, status_code=400, error_message=str(exc))
    finally:
        conn.close()

    message = f"Tag removed: {tag_name}" if removed else f"No matching tag: {tag_name}"
    return _redirect_with_message(f"/papers/{paper_id}", ok=message)


@router.post("/papers/{paper_id}/notes/create", response_class=HTMLResponse)
def paper_note_create(request: Request, paper_id: str):
    cfg = get_app_config(request)
    conn = open_db(request)
    try:
        row = conn.execute(
            "SELECT title FROM papers WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id}")
        title = row["title"] if isinstance(row, sqlite3.Row) else row[0]
        note = init_note_from_template(
            conn,
            paper_id,
            cfg.notes_root,
            title=title or "",
            template_path=cfg.template_path if cfg.template_path else None,
        )
        index_paper(conn, paper_id)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        return render_paper_detail_page(request, paper_id, status_code=400, error_message=str(exc))
    finally:
        conn.close()

    return _redirect_with_message(f"/papers/{paper_id}", ok=f"Note ready: {note.note_id}")


@router.post("/papers/{paper_id}/validations", response_class=HTMLResponse)
def paper_validation_create(
    request: Request,
    paper_id: str,
    path: str | None = Form(default=None),
    repo_url: str | None = Form(default=None),
    environment_note: str | None = Form(default=None),
):
    conn = open_db(request)
    try:
        record = create_validation(
            conn,
            paper_id,
            path=path or None,
            repo_url=repo_url or None,
            environment_note=environment_note or None,
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        return render_paper_detail_page(request, paper_id, status_code=400, error_message=str(exc))
    finally:
        conn.close()

    return _redirect_with_message(f"/papers/{paper_id}", ok=f"Validation created: {record.validation_id}")


@router.post("/papers/{paper_id}/files/{file_id}/open", response_class=HTMLResponse)
def paper_file_open(request: Request, paper_id: str, file_id: str):
    conn = open_db(request)
    try:
        row = conn.execute(
            """
            SELECT absolute_path FROM file_assets
            WHERE paper_id = ? AND file_id = ?
            """,
            (paper_id, file_id),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"File asset {file_id!r} not found for paper {paper_id!r}")

    absolute_path = Path(row[0])
    if not absolute_path.exists():
        return render_paper_detail_page(
            request,
            paper_id,
            status_code=400,
            error_message=f"Registered file path does not exist: {absolute_path}",
        )

    try:
        _open_local_file(absolute_path)
    except LocalOpenError as exc:
        return render_paper_detail_page(
            request,
            paper_id,
            status_code=400,
            error_message=str(exc),
        )

    message = f"Open request sent for {absolute_path.name}."
    return RedirectResponse(
        url=f"/papers/{paper_id}?{urlencode({'ok': message})}",
        status_code=303,
    )
