"""Minimal tag lifecycle management."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from artimanager.db.utils import new_id


def _normalize_tag_name(name: str) -> str:
    normalized = " ".join(name.split())
    if not normalized:
        raise ValueError("Tag name cannot be empty.")
    return normalized


@dataclass
class TagRecord:
    tag_id: str
    name: str
    tag_type: str | None
    source: str


def _find_tag_by_name(conn: sqlite3.Connection, name: str) -> TagRecord | None:
    """Find a tag by normalized, case-insensitive name."""
    row = conn.execute(
        """SELECT tag_id, name, tag_type, source
           FROM tags
           WHERE lower(name) = lower(?)
           LIMIT 1""",
        (name,),
    ).fetchone()
    if row is None:
        return None
    return TagRecord(*row)


def add_tag_to_paper(
    conn: sqlite3.Connection,
    paper_id: str,
    tag_name: str,
    *,
    tag_type: str | None = None,
) -> TagRecord:
    """Create/resolve a tag and link it to a paper as user-confirmed."""
    paper_row = conn.execute(
        "SELECT 1 FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if paper_row is None:
        raise ValueError(f"Paper not found: {paper_id}")

    name = _normalize_tag_name(tag_name)
    ttype = " ".join(tag_type.split()) if tag_type and " ".join(tag_type.split()) else None

    tag = _find_tag_by_name(conn, name)
    if tag is None:
        tag = TagRecord(
            tag_id=new_id(),
            name=name,
            tag_type=ttype,
            source="user",
        )
        conn.execute(
            "INSERT INTO tags (tag_id, name, tag_type, source) VALUES (?, ?, ?, ?)",
            (tag.tag_id, tag.name, tag.tag_type, tag.source),
        )
    elif tag.tag_type is None and ttype:
        # Keep first normalized display name; only fill empty type.
        conn.execute(
            "UPDATE tags SET tag_type = ? WHERE tag_id = ?",
            (ttype, tag.tag_id),
        )
        tag = TagRecord(tag_id=tag.tag_id, name=tag.name, tag_type=ttype, source=tag.source)

    conn.execute(
        """INSERT INTO paper_tags (paper_id, tag_id, confidence, confirmed_by_user)
           VALUES (?, ?, NULL, 1)
           ON CONFLICT(paper_id, tag_id)
           DO UPDATE SET confirmed_by_user = 1""",
        (paper_id, tag.tag_id),
    )
    return tag


def remove_tag_from_paper(
    conn: sqlite3.Connection,
    paper_id: str,
    tag_name: str,
) -> bool:
    """Remove one paper-tag link by normalized tag name."""
    name = _normalize_tag_name(tag_name)
    tag = _find_tag_by_name(conn, name)
    if tag is None:
        return False
    cur = conn.execute(
        "DELETE FROM paper_tags WHERE paper_id = ? AND tag_id = ?",
        (paper_id, tag.tag_id),
    )
    return cur.rowcount > 0


def list_tags_for_paper(
    conn: sqlite3.Connection,
    paper_id: str,
) -> list[TagRecord]:
    """List tags attached to one paper."""
    rows = conn.execute(
        """SELECT t.tag_id, t.name, t.tag_type, t.source
           FROM paper_tags pt
           JOIN tags t ON t.tag_id = pt.tag_id
           WHERE pt.paper_id = ?
           ORDER BY lower(t.name), t.name""",
        (paper_id,),
    ).fetchall()
    return [TagRecord(*row) for row in rows]
