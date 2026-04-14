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
from artimanager.scanner.extract import PaperMetadata, PymupdfExtractor, TextExtractor
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
    status: str  # "new" | "duplicate" | "failed"
    message: str = ""


@dataclass
class IntakeReport:
    """Summary of an intake run."""

    new_count: int = 0
    duplicate_count: int = 0
    failed_count: int = 0
    details: list[IntakeDetail] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.new_count + self.duplicate_count + self.failed_count


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
        "SELECT file_id FROM file_assets WHERE absolute_path = ?",
        (candidate.absolute_path,),
    ).fetchone()
    if existing:
        # Already imported this exact path — skip silently
        return

    # --- Extract metadata ---
    try:
        metadata = extractor.extract_metadata(candidate.absolute_path)
    except Exception as exc:
        logger.warning("Metadata extraction failed for %s: %s", candidate.filename, exc)
        metadata = PaperMetadata()

    # --- Extract full text ---
    try:
        full_text = extractor.extract_full_text(candidate.absolute_path)
    except Exception as exc:
        logger.warning("Full text extraction failed for %s: %s", candidate.filename, exc)
        full_text = None

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
        report.duplicate_count += 1
        report.details.append(
            IntakeDetail(
                path=candidate.absolute_path,
                paper_id=paper_id,
                status="duplicate",
                message=f"Matched existing paper(s): {', '.join(dup_ids)}",
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
