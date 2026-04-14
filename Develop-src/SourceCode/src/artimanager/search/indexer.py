"""Search index management — build and rebuild FTS5 indexes.

FTS5 indexes are derived projections and can be fully rebuilt
from source data (papers + file_assets tables).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class IndexReport:
    """Summary of an indexing operation."""

    papers_indexed: int = 0
    fulltext_indexed: int = 0
    notes_indexed: int = 0


def rebuild_search_index(conn: sqlite3.Connection) -> IndexReport:
    """Drop and recreate all FTS5 index content from source tables.

    Parameters
    ----------
    conn:
        Open database connection (tables must already exist).

    Returns
    -------
    IndexReport with counts of indexed records.
    """
    report = IndexReport()

    # Clear existing FTS data
    conn.execute("DELETE FROM papers_fts")
    conn.execute("DELETE FROM fulltext_fts")
    conn.execute("DELETE FROM notes_fts")

    # Populate papers_fts from papers table
    rows = conn.execute(
        "SELECT paper_id, title, authors, abstract FROM papers"
    ).fetchall()
    for r in rows:
        authors_str = ""
        if r[2]:
            try:
                authors_str = ", ".join(json.loads(r[2]))
            except (json.JSONDecodeError, TypeError):
                authors_str = r[2] or ""

        conn.execute(
            "INSERT INTO papers_fts (paper_id, title, authors, abstract) VALUES (?, ?, ?, ?)",
            (r[0], r[1] or "", authors_str, r[3] or ""),
        )
        report.papers_indexed += 1

    # Populate fulltext_fts — one entry per paper_id (first file with full_text)
    rows = conn.execute(
        """SELECT paper_id, full_text FROM file_assets
           WHERE full_text IS NOT NULL AND full_text != ''
           GROUP BY paper_id"""
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO fulltext_fts (paper_id, full_text) VALUES (?, ?)",
            (r[0], r[1]),
        )
        report.fulltext_indexed += 1

    # Populate notes_fts from markdown notes on disk
    rows = conn.execute(
        """SELECT n.paper_id, n.title, n.location
           FROM notes n
           WHERE n.note_type = 'markdown_note'"""
    ).fetchall()
    for r in rows:
        paper_id, title, location = r
        if not location:
            continue
        path = Path(location)
        if not path.exists():
            logger.warning("Skipping missing note file for indexing: %s", location)
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            logger.warning("Skipping unreadable note file for indexing: %s", location)
            continue
        conn.execute(
            "INSERT INTO notes_fts (paper_id, note_title, note_content) VALUES (?, ?, ?)",
            (paper_id, title or path.name, content),
        )
        report.notes_indexed += 1

    conn.commit()
    logger.info(
        "Search index rebuilt: %d papers, %d fulltext, %d notes",
        report.papers_indexed, report.fulltext_indexed, report.notes_indexed,
    )
    return report


def index_paper(conn: sqlite3.Connection, paper_id: str) -> None:
    """Incrementally index a single paper into FTS5 tables.

    Replaces any existing FTS entry for this paper_id.
    """
    # Remove old entries
    conn.execute("DELETE FROM papers_fts WHERE paper_id = ?", (paper_id,))
    conn.execute("DELETE FROM fulltext_fts WHERE paper_id = ?", (paper_id,))
    conn.execute("DELETE FROM notes_fts WHERE paper_id = ?", (paper_id,))

    # Index metadata
    row = conn.execute(
        "SELECT title, authors, abstract FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row:
        authors_str = ""
        if row[1]:
            try:
                authors_str = ", ".join(json.loads(row[1]))
            except (json.JSONDecodeError, TypeError):
                authors_str = row[1] or ""
        conn.execute(
            "INSERT INTO papers_fts (paper_id, title, authors, abstract) VALUES (?, ?, ?, ?)",
            (paper_id, row[0] or "", authors_str, row[2] or ""),
        )

    # Index full text
    ft_row = conn.execute(
        """SELECT full_text FROM file_assets
           WHERE paper_id = ? AND full_text IS NOT NULL AND full_text != ''
           LIMIT 1""",
        (paper_id,),
    ).fetchone()
    if ft_row:
        conn.execute(
            "INSERT INTO fulltext_fts (paper_id, full_text) VALUES (?, ?)",
            (paper_id, ft_row[0]),
        )

    # Index markdown note content when note file exists
    note_row = conn.execute(
        """SELECT title, location FROM notes
           WHERE paper_id = ? AND note_type = 'markdown_note'
           LIMIT 1""",
        (paper_id,),
    ).fetchone()
    if note_row and note_row[1]:
        note_path = Path(note_row[1])
        if note_path.exists():
            try:
                note_content = note_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                note_content = ""
            if note_content:
                conn.execute(
                    "INSERT INTO notes_fts (paper_id, note_title, note_content) VALUES (?, ?, ?)",
                    (paper_id, note_row[0] or note_path.name, note_content),
                )
