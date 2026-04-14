"""Tests for scanner.dedup — duplicate detection."""

from __future__ import annotations

import json
import sqlite3

import pytest

from artimanager.scanner.dedup import _normalise_title, find_duplicates
from artimanager.scanner.extract import PaperMetadata
from artimanager.scanner.scan import FileCandidate


def _make_candidate(
    sha256: str = "abc123",
    path: str = "/tmp/test.pdf",
) -> FileCandidate:
    return FileCandidate(
        absolute_path=path,
        filename="test.pdf",
        filesize=1000,
        sha256=sha256,
        mime_type="application/pdf",
    )


def _insert_paper(
    conn: sqlite3.Connection,
    paper_id: str = "p1",
    title: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO papers (paper_id, title, doi, arxiv_id, workflow_status)
           VALUES (?, ?, ?, ?, 'inbox')""",
        (paper_id, title, doi, arxiv_id),
    )


def _insert_file(
    conn: sqlite3.Connection,
    file_id: str = "f1",
    paper_id: str = "p1",
    sha256: str = "abc123",
) -> None:
    conn.execute(
        """INSERT INTO file_assets (file_id, paper_id, absolute_path, filename, sha256)
           VALUES (?, ?, '/tmp/existing.pdf', 'existing.pdf', ?)""",
        (file_id, paper_id, sha256),
    )


class TestNormaliseTitle:
    def test_basic(self) -> None:
        assert _normalise_title("Hello World!") == "helloworld"

    def test_strips_punctuation(self) -> None:
        assert _normalise_title("A.B-C (D)") == "abcd"

    def test_unicode_stripped(self) -> None:
        assert _normalise_title("café") == "caf"


class TestFindDuplicates:
    """find_duplicates() priority-based matching."""

    def test_match_by_sha256(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1")
        _insert_file(db_conn, "f1", "p1", sha256="deadbeef")
        db_conn.commit()

        candidate = _make_candidate(sha256="deadbeef")
        meta = PaperMetadata()
        result = find_duplicates(candidate, meta, db_conn)
        assert result == ["p1"]

    def test_match_by_doi(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", doi="10.1234/test")
        db_conn.commit()

        candidate = _make_candidate(sha256="unique")
        meta = PaperMetadata(doi="10.1234/test")
        result = find_duplicates(candidate, meta, db_conn)
        assert result == ["p1"]

    def test_match_by_arxiv_id(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", arxiv_id="1803.02029")
        db_conn.commit()

        candidate = _make_candidate(sha256="unique")
        meta = PaperMetadata(arxiv_id="1803.02029")
        result = find_duplicates(candidate, meta, db_conn)
        assert result == ["p1"]

    def test_match_by_title(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", title="A Long Enough Title For Matching")
        db_conn.commit()

        candidate = _make_candidate(sha256="unique")
        meta = PaperMetadata(title="A Long Enough Title For Matching")
        result = find_duplicates(candidate, meta, db_conn)
        assert result == ["p1"]

    def test_title_too_short_skipped(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", title="Short")
        db_conn.commit()

        candidate = _make_candidate(sha256="unique")
        meta = PaperMetadata(title="Short")
        result = find_duplicates(candidate, meta, db_conn)
        assert result == []

    def test_no_match(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", title="Existing Paper Title Here")
        db_conn.commit()

        candidate = _make_candidate(sha256="unique")
        meta = PaperMetadata(title="Completely Different Paper")
        result = find_duplicates(candidate, meta, db_conn)
        assert result == []

    def test_dedup_across_signals(self, db_conn: sqlite3.Connection) -> None:
        """Same paper matched by both DOI and arXiv — should appear once."""
        _insert_paper(db_conn, "p1", doi="10.1234/x", arxiv_id="2301.00001")
        db_conn.commit()

        candidate = _make_candidate(sha256="unique")
        meta = PaperMetadata(doi="10.1234/x", arxiv_id="2301.00001")
        result = find_duplicates(candidate, meta, db_conn)
        assert result == ["p1"]
