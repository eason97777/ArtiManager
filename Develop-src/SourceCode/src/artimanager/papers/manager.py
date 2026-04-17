"""Shared paper update rules for CLI and web actions."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from artimanager.db.utils import now_iso

WORKFLOW_STATUS_VALUES = ("inbox", "active", "archived", "ignored")
READING_STATE_VALUES = ("to_read", "reading", "read", "skimmed", "deferred")
RESEARCH_STATE_VALUES = ("untriaged", "relevant", "background", "maybe", "not_relevant")

_MISSING = object()


def _ensure_paper_exists(conn: sqlite3.Connection, paper_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Paper not found: {paper_id}")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _clean_abstract(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", str(value))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or None


def _parse_authors(value: str | list[str] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        authors = [" ".join(str(item).split()) for item in value]
    else:
        authors = [
            " ".join(item.split())
            for item in re.split(r"\n|;", value.replace(",", "\n"))
        ]
    authors = [item for item in authors if item]
    return json.dumps(authors) if authors else None


def _parse_year(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Year must be an integer.") from exc
    if year < 1000 or year > 9999:
        raise ValueError("Year must be a four-digit integer.")
    return year


def _apply_updates(
    conn: sqlite3.Connection,
    paper_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    if not updates:
        raise ValueError("No paper fields provided.")

    updates["updated_at"] = now_iso()
    set_clause = ", ".join(f"{field} = ?" for field in updates)
    conn.execute(
        f"UPDATE papers SET {set_clause} WHERE paper_id = ?",
        list(updates.values()) + [paper_id],
    )
    return {key: value for key, value in updates.items() if key != "updated_at"}


def update_paper_state(
    conn: sqlite3.Connection,
    paper_id: str,
    *,
    workflow_status: str | None = None,
    reading_state: str | None = None,
    research_state: str | None = None,
) -> dict[str, Any]:
    """Update controlled paper triage states."""
    _ensure_paper_exists(conn, paper_id)
    updates: dict[str, Any] = {}

    if workflow_status is not None:
        if workflow_status not in WORKFLOW_STATUS_VALUES:
            raise ValueError(f"Invalid workflow_status: {workflow_status}")
        updates["workflow_status"] = workflow_status
    if reading_state is not None:
        if reading_state not in READING_STATE_VALUES:
            raise ValueError(f"Invalid reading_state: {reading_state}")
        updates["reading_state"] = reading_state
    if research_state is not None:
        if research_state not in RESEARCH_STATE_VALUES:
            raise ValueError(f"Invalid research_state: {research_state}")
        updates["research_state"] = research_state

    return _apply_updates(conn, paper_id, updates)


def update_paper_metadata(
    conn: sqlite3.Connection,
    paper_id: str,
    *,
    title: str | object = _MISSING,
    authors: str | list[str] | object = _MISSING,
    year: str | int | object = _MISSING,
    doi: str | object = _MISSING,
    arxiv_id: str | object = _MISSING,
    abstract: str | object = _MISSING,
) -> dict[str, Any]:
    """Update manually correctable paper metadata fields."""
    _ensure_paper_exists(conn, paper_id)
    updates: dict[str, Any] = {}

    if title is not _MISSING:
        updates["title"] = _clean_text(title if isinstance(title, str) else None)
    if authors is not _MISSING:
        if not (isinstance(authors, str) or isinstance(authors, list) or authors is None):
            raise ValueError("Authors must be text or a list of strings.")
        updates["authors"] = _parse_authors(authors)
    if year is not _MISSING:
        if not (isinstance(year, str) or isinstance(year, int) or year is None):
            raise ValueError("Year must be text or an integer.")
        updates["year"] = _parse_year(year)
    if doi is not _MISSING:
        updates["doi"] = _clean_text(doi if isinstance(doi, str) else None)
    if arxiv_id is not _MISSING:
        updates["arxiv_id"] = _clean_text(arxiv_id if isinstance(arxiv_id, str) else None)
    if abstract is not _MISSING:
        updates["abstract"] = _clean_abstract(abstract if isinstance(abstract, str) else None)

    return _apply_updates(conn, paper_id, updates)
