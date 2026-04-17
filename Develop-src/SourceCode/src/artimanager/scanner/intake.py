"""Intake pipeline — orchestrate scan → extract → dedup → store.

Safety contract: never moves, renames, or deletes user files.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from artimanager.config import AppConfig
from artimanager.db.utils import new_id, now_iso
from artimanager.scanner.dedup import find_duplicates
from artimanager.scanner.extract import (
    PaperMetadata,
    PymupdfExtractor,
    TextExtractor,
    is_low_quality_title,
)
from artimanager.scanner.scan import FileCandidate, scan_folder
from artimanager.search.indexer import index_paper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class IntakeDetail:
    """Per-file outcome."""

    path: str
    paper_id: str
    status: str  # "new" | "duplicate" | "updated" | "unchanged" | "failed"
    message: str = ""


@dataclass
class IntakeReport:
    """Summary of an intake run."""

    new_count: int = 0
    duplicate_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    failed_count: int = 0
    details: list[IntakeDetail] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.new_count
            + self.duplicate_count
            + self.updated_count
            + self.unchanged_count
            + self.failed_count
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Pipeline
# ---------------------------------------------------------------------------

def run_intake(
    config: AppConfig,
    conn: sqlite3.Connection,
    *,
    extractor: TextExtractor | None = None,
    progress: Callable[[FileCandidate], None] | None = None,
) -> IntakeReport:
    """Execute the full intake pipeline.

    Parameters
    ----------
    config:
        Application configuration (provides ``scan_folders``).
    conn:
        Open database connection (tables must already exist).
    extractor:
        Text extraction backend.  Defaults to ``PymupdfExtractor``.
    progress:
        Optional callback invoked once for each discovered PDF candidate before
        processing starts.

    Returns
    -------
    IntakeReport summarising what happened.
    """
    if extractor is None:
        extractor = PymupdfExtractor()

    report = IntakeReport()

    for folder in config.scan_folders:
        try:
            candidates = scan_folder(folder)
        except FileNotFoundError as exc:
            logger.warning("Skipping folder: %s", exc)
            continue

        for candidate in candidates:
            if progress is not None:
                progress(candidate)
            _process_candidate(candidate, conn, extractor, report)

    conn.commit()
    return report


def _process_candidate(
    candidate: FileCandidate,
    conn: sqlite3.Connection,
    extractor: TextExtractor,
    report: IntakeReport,
) -> None:
    """Process a single file candidate through the pipeline."""

    # --- Check if this exact file is already in the database ---
    existing = conn.execute(
        """
        SELECT file_id, paper_id, sha256, filesize
        FROM file_assets
        WHERE absolute_path = ?
        """,
        (candidate.absolute_path,),
    ).fetchone()
    if existing:
        _process_existing_path(candidate, conn, extractor, report, existing)
        return

    # --- Extract metadata ---
    metadata, full_text = _extract_candidate(candidate, extractor)

    # --- Dedup ---
    try:
        dup_ids = find_duplicates(candidate, metadata, conn)
    except Exception as exc:
        logger.warning("Dedup check failed for %s: %s", candidate.filename, exc)
        dup_ids = []

    now = now_iso()

    if dup_ids:
        # Duplicate — attach file to first matching paper
        paper_id = dup_ids[0]
        file_id = new_id()
        _insert_file_asset(
            conn,
            file_id=file_id,
            paper_id=paper_id,
            candidate=candidate,
            metadata=metadata,
            full_text=full_text,
            import_status="duplicate",
            now=now,
        )
        repair_messages = _repair_paper_metadata(conn, paper_id, metadata, now)
        index_paper(conn, paper_id)
        report.duplicate_count += 1
        report.details.append(
            IntakeDetail(
                path=candidate.absolute_path,
                paper_id=paper_id,
                status="duplicate",
                message="; ".join(
                    [f"Matched existing paper(s): {', '.join(dup_ids)}"]
                    + repair_messages
                ),
            )
        )
    else:
        # New paper
        paper_id = new_id()
        file_id = new_id()
        try:
            _insert_paper(conn, paper_id, metadata, now)
            _insert_file_asset(
                conn,
                file_id=file_id,
                paper_id=paper_id,
                candidate=candidate,
                metadata=metadata,
                full_text=full_text,
                import_status="new",
                now=now,
            )
            index_paper(conn, paper_id)
            report.new_count += 1
            report.details.append(
                IntakeDetail(
                    path=candidate.absolute_path,
                    paper_id=paper_id,
                    status="new",
                )
            )
        except Exception as exc:
            logger.error("Failed to store %s: %s", candidate.filename, exc)
            report.failed_count += 1
            report.details.append(
                IntakeDetail(
                    path=candidate.absolute_path,
                    paper_id="",
                    status="failed",
                    message=str(exc),
                )
            )


def _extract_candidate(
    candidate: FileCandidate,
    extractor: TextExtractor,
) -> tuple[PaperMetadata, str | None]:
    try:
        metadata = extractor.extract_metadata(candidate.absolute_path)
    except Exception as exc:
        logger.warning("Metadata extraction failed for %s: %s", candidate.filename, exc)
        metadata = PaperMetadata()

    try:
        full_text = extractor.extract_full_text(candidate.absolute_path)
    except Exception as exc:
        logger.warning("Full text extraction failed for %s: %s", candidate.filename, exc)
        full_text = None

    return metadata, full_text


def _process_existing_path(
    candidate: FileCandidate,
    conn: sqlite3.Connection,
    extractor: TextExtractor,
    report: IntakeReport,
    existing,
) -> None:
    file_id = existing["file_id"] if isinstance(existing, sqlite3.Row) else existing[0]
    paper_id = existing["paper_id"] if isinstance(existing, sqlite3.Row) else existing[1]
    old_sha256 = existing["sha256"] if isinstance(existing, sqlite3.Row) else existing[2]
    old_filesize = existing["filesize"] if isinstance(existing, sqlite3.Row) else existing[3]

    if old_sha256 == candidate.sha256 and old_filesize == candidate.filesize:
        report.unchanged_count += 1
        report.details.append(
            IntakeDetail(
                path=candidate.absolute_path,
                paper_id=paper_id,
                status="unchanged",
                message="Already current",
            )
        )
        return

    metadata, full_text = _extract_candidate(candidate, extractor)
    now = now_iso()
    _update_file_asset(
        conn,
        file_id=file_id,
        candidate=candidate,
        metadata=metadata,
        full_text=full_text,
    )
    messages = ["Refreshed existing file asset"]
    messages.extend(_metadata_conflict_messages(conn, paper_id, metadata))
    messages.extend(_repair_paper_metadata(conn, paper_id, metadata, now))
    index_paper(conn, paper_id)

    report.updated_count += 1
    report.details.append(
        IntakeDetail(
            path=candidate.absolute_path,
            paper_id=paper_id,
            status="updated",
            message="; ".join(messages),
        )
    )


def _metadata_conflict_messages(
    conn: sqlite3.Connection,
    paper_id: str,
    metadata: PaperMetadata,
) -> list[str]:
    row = conn.execute(
        "SELECT doi, arxiv_id FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        return []

    messages: list[str] = []
    existing_doi = row["doi"] if isinstance(row, sqlite3.Row) else row[0]
    existing_arxiv = row["arxiv_id"] if isinstance(row, sqlite3.Row) else row[1]
    if existing_doi and metadata.doi and existing_doi != metadata.doi:
        messages.append(f"warning: extracted DOI {metadata.doi} conflicts with linked paper DOI {existing_doi}")
    if existing_arxiv and metadata.arxiv_id and existing_arxiv != metadata.arxiv_id:
        messages.append(
            f"warning: extracted arXiv {metadata.arxiv_id} conflicts with linked paper arXiv {existing_arxiv}"
        )
    return messages


def _repair_paper_metadata(
    conn: sqlite3.Connection,
    paper_id: str,
    metadata: PaperMetadata,
    now: str,
) -> list[str]:
    row = conn.execute(
        """
        SELECT title, authors, year, doi, arxiv_id, abstract
        FROM papers WHERE paper_id = ?
        """,
        (paper_id,),
    ).fetchone()
    if row is None:
        return []

    values = dict(row) if isinstance(row, sqlite3.Row) else {
        "title": row[0],
        "authors": row[1],
        "year": row[2],
        "doi": row[3],
        "arxiv_id": row[4],
        "abstract": row[5],
    }
    updates: dict[str, object] = {}

    if metadata.title and (
        not values["title"] or is_low_quality_title(str(values["title"]))
    ) and not is_low_quality_title(metadata.title):
        updates["title"] = metadata.title

    if metadata.authors and not values["authors"]:
        updates["authors"] = json.dumps(metadata.authors)
    if metadata.year and values["year"] is None:
        updates["year"] = metadata.year
    if metadata.doi and not values["doi"]:
        updates["doi"] = metadata.doi
    if metadata.arxiv_id and not values["arxiv_id"]:
        updates["arxiv_id"] = metadata.arxiv_id
    if metadata.abstract and not values["abstract"]:
        updates["abstract"] = metadata.abstract

    if not updates:
        return []

    updates["updated_at"] = now
    set_clause = ", ".join(f"{field} = ?" for field in updates)
    conn.execute(
        f"UPDATE papers SET {set_clause} WHERE paper_id = ?",
        list(updates.values()) + [paper_id],
    )
    index_paper(conn, paper_id)
    fields = ", ".join(field for field in updates if field != "updated_at")
    return [f"repaired metadata fields: {fields}"]


def _insert_paper(
    conn: sqlite3.Connection,
    paper_id: str,
    metadata: PaperMetadata,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO papers
            (paper_id, title, authors, year, doi, arxiv_id, abstract,
             workflow_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'inbox', ?, ?)
        """,
        (
            paper_id,
            metadata.title or None,
            json.dumps(metadata.authors) if metadata.authors else None,
            metadata.year,
            metadata.doi or None,
            metadata.arxiv_id or None,
            metadata.abstract or None,
            now,
            now,
        ),
    )


def _insert_file_asset(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    paper_id: str,
    candidate: FileCandidate,
    metadata: PaperMetadata,
    full_text: str | None,
    import_status: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO file_assets
            (file_id, paper_id, absolute_path, filename, sha256, filesize,
             mime_type, detected_title, detected_year,
             full_text_extracted, full_text, import_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            paper_id,
            candidate.absolute_path,
            candidate.filename,
            candidate.sha256,
            candidate.filesize,
            candidate.mime_type,
            metadata.title or None,
            metadata.year,
            1 if full_text else 0,
            full_text,
            import_status,
            now,
        ),
    )


def _update_file_asset(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    candidate: FileCandidate,
    metadata: PaperMetadata,
    full_text: str | None,
) -> None:
    conn.execute(
        """
        UPDATE file_assets
        SET sha256 = ?,
            filesize = ?,
            mime_type = ?,
            detected_title = ?,
            detected_year = ?,
            full_text_extracted = ?,
            full_text = ?,
            import_status = 'updated'
        WHERE file_id = ?
        """,
        (
            candidate.sha256,
            candidate.filesize,
            candidate.mime_type,
            metadata.title or None,
            metadata.year,
            1 if full_text else 0,
            full_text,
            file_id,
        ),
    )
