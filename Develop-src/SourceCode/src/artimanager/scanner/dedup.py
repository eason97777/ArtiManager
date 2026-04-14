"""Duplicate detection for incoming files.

Checks against existing database records by (in priority order):
1. SHA-256 file hash (exact duplicate)
2. DOI
3. arXiv ID
4. Title similarity (normalised comparison)
"""

from __future__ import annotations

import re
import sqlite3

from artimanager.scanner.extract import PaperMetadata
from artimanager.scanner.scan import FileCandidate


def _normalise_title(title: str) -> str:
    """Lowercase, strip punctuation and whitespace for fuzzy compare."""
    return re.sub(r"[^a-z0-9]", "", title.lower())


def find_duplicates(
    candidate: FileCandidate,
    metadata: PaperMetadata,
    conn: sqlite3.Connection,
) -> list[str]:
    """Return paper_ids of likely duplicate records.

    Parameters
    ----------
    candidate:
        The file being ingested.
    metadata:
        Extracted metadata for the file.
    conn:
        Open database connection.

    Returns
    -------
    List of matching ``paper_id`` strings (empty if no duplicate found).
    The list may contain more than one entry if multiple signals match
    different papers — the caller decides how to resolve.
    """
    matches: list[str] = []
    seen: set[str] = set()

    def _add(paper_id: str) -> None:
        if paper_id not in seen:
            seen.add(paper_id)
            matches.append(paper_id)

    # 1. SHA-256 — exact file duplicate
    row = conn.execute(
        "SELECT paper_id FROM file_assets WHERE sha256 = ?",
        (candidate.sha256,),
    ).fetchone()
    if row:
        _add(row[0])

    # 2. DOI
    if metadata.doi:
        row = conn.execute(
            "SELECT paper_id FROM papers WHERE doi = ?",
            (metadata.doi,),
        ).fetchone()
        if row:
            _add(row[0])

    # 3. arXiv ID
    if metadata.arxiv_id:
        row = conn.execute(
            "SELECT paper_id FROM papers WHERE arxiv_id = ?",
            (metadata.arxiv_id,),
        ).fetchone()
        if row:
            _add(row[0])

    # 4. Title similarity (normalised exact match)
    if metadata.title:
        norm = _normalise_title(metadata.title)
        if len(norm) > 10:  # skip very short / empty titles
            rows = conn.execute(
                "SELECT paper_id, title FROM papers WHERE title IS NOT NULL",
            ).fetchall()
            for r in rows:
                if _normalise_title(r[1]) == norm:
                    _add(r[0])

    return matches
