"""Tests for scanner.intake — end-to-end intake pipeline."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from artimanager.config import AppConfig
from artimanager.scanner.extract import PaperMetadata, TextExtractor
from artimanager.scanner.intake import IntakeReport, run_intake

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
REAL_PDF = DATA_DIR / "1803.02029v1.pdf"


class FakeExtractor:
    """Deterministic extractor for unit tests."""

    def __init__(self, meta: PaperMetadata | None = None) -> None:
        self._meta = meta or PaperMetadata(
            title="Fake Paper Title For Testing",
            authors=["Author A", "Author B"],
            year=2023,
            doi="10.9999/fake",
        )

    def extract_metadata(self, pdf_path: str | Path) -> PaperMetadata:
        return self._meta

    def extract_full_text(self, pdf_path: str | Path) -> str | None:
        return "Fake full text content for testing purposes."


class TestRunIntake:
    """run_intake() pipeline tests."""

    def _make_config(self, tmp_path: Path) -> AppConfig:
        papers = tmp_path / "papers"
        papers.mkdir()
        return AppConfig(
            scan_folders=[str(papers)],
            db_path=str(tmp_path / "test.db"),
            notes_root=str(tmp_path / "notes"),
        )

    def _setup(self, tmp_path: Path) -> tuple[AppConfig, sqlite3.Connection]:
        from artimanager.db.connection import get_connection, init_db

        cfg = self._make_config(tmp_path)
        init_db(cfg.db_path)
        conn = get_connection(cfg.db_path)
        return cfg, conn

    def test_empty_folder(self, tmp_path: Path) -> None:
        cfg, conn = self._setup(tmp_path)
        try:
            report = run_intake(cfg, conn, extractor=FakeExtractor())
            assert report.total == 0
            assert report.new_count == 0
        finally:
            conn.close()

    def test_new_paper_ingested(self, tmp_path: Path) -> None:
        cfg, conn = self._setup(tmp_path)
        papers_dir = Path(cfg.scan_folders[0])
        (papers_dir / "test.pdf").write_bytes(b"%PDF-1.4 test content")
        try:
            report = run_intake(cfg, conn, extractor=FakeExtractor())
            assert report.new_count == 1
            assert report.duplicate_count == 0
            assert report.total == 1

            row = conn.execute("SELECT title, workflow_status FROM papers").fetchone()
            assert row[0] == "Fake Paper Title For Testing"
            assert row[1] == "inbox"

            fa = conn.execute("SELECT full_text FROM file_assets").fetchone()
            assert fa[0] is not None
        finally:
            conn.close()

    def test_duplicate_detected_on_rescan(self, tmp_path: Path) -> None:
        cfg, conn = self._setup(tmp_path)
        papers_dir = Path(cfg.scan_folders[0])
        (papers_dir / "test.pdf").write_bytes(b"%PDF-1.4 dup content")
        try:
            r1 = run_intake(cfg, conn, extractor=FakeExtractor())
            assert r1.new_count == 1

            # Copy same file to a different name
            (papers_dir / "test_copy.pdf").write_bytes(b"%PDF-1.4 dup content")
            r2 = run_intake(cfg, conn, extractor=FakeExtractor())
            assert r2.duplicate_count == 1
            assert r2.new_count == 0
        finally:
            conn.close()

    def test_same_path_skipped_silently(self, tmp_path: Path) -> None:
        cfg, conn = self._setup(tmp_path)
        papers_dir = Path(cfg.scan_folders[0])
        (papers_dir / "test.pdf").write_bytes(b"%PDF-1.4 same path")
        try:
            r1 = run_intake(cfg, conn, extractor=FakeExtractor())
            assert r1.new_count == 1

            # Re-scan same file — should be skipped entirely
            r2 = run_intake(cfg, conn, extractor=FakeExtractor())
            assert r2.total == 0
        finally:
            conn.close()

    def test_progress_callback_invoked_for_each_candidate(self, tmp_path: Path) -> None:
        cfg, conn = self._setup(tmp_path)
        papers_dir = Path(cfg.scan_folders[0])
        (papers_dir / "a.pdf").write_bytes(b"%PDF-1.4 aaa")
        (papers_dir / "b.pdf").write_bytes(b"%PDF-1.4 bbb")
        seen: list[str] = []
        try:
            run_intake(
                cfg,
                conn,
                extractor=FakeExtractor(),
                progress=lambda candidate: seen.append(candidate.filename),
            )
            assert seen == ["a.pdf", "b.pdf"]
        finally:
            conn.close()

    def test_missing_folder_skipped(self, tmp_path: Path) -> None:
        from artimanager.db.connection import get_connection, init_db

        cfg = AppConfig(
            scan_folders=[str(tmp_path / "nonexistent")],
            db_path=str(tmp_path / "test.db"),
            notes_root=str(tmp_path / "notes"),
        )
        init_db(cfg.db_path)
        conn = get_connection(cfg.db_path)
        try:
            report = run_intake(cfg, conn, extractor=FakeExtractor())
            assert report.total == 0
        finally:
            conn.close()

    def test_report_details_populated(self, tmp_path: Path) -> None:
        cfg, conn = self._setup(tmp_path)
        papers_dir = Path(cfg.scan_folders[0])
        (papers_dir / "a.pdf").write_bytes(b"%PDF-1.4 aaa")
        (papers_dir / "b.pdf").write_bytes(b"%PDF-1.4 bbb")
        try:
            report = run_intake(cfg, conn, extractor=FakeExtractor())
            assert len(report.details) == 2
            statuses = {d.status for d in report.details}
            # Both are "new" on first scan (different sha256 but same DOI → second is dup)
            assert statuses <= {"new", "duplicate"}
        finally:
            conn.close()


@pytest.mark.skipif(not REAL_PDF.exists(), reason="test PDF not available")
class TestIntakeRealPdf:
    """Integration test with real PDF."""

    def test_real_pdf_intake(self, tmp_path: Path) -> None:
        from artimanager.db.connection import get_connection, init_db

        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        shutil.copy2(REAL_PDF, papers_dir / "1803.02029v1.pdf")

        cfg = AppConfig(
            scan_folders=[str(papers_dir)],
            db_path=str(tmp_path / "test.db"),
            notes_root=str(tmp_path / "notes"),
        )
        init_db(cfg.db_path)
        conn = get_connection(cfg.db_path)
        try:
            report = run_intake(cfg, conn)
            assert report.new_count == 1
            assert report.failed_count == 0

            row = conn.execute("SELECT title FROM papers").fetchone()
            assert row[0]  # title should be non-empty
        finally:
            conn.close()
