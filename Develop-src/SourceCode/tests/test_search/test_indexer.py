"""Tests for search.indexer — FTS5 index build and rebuild."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from artimanager.search.indexer import IndexReport, index_paper, rebuild_search_index


def _insert_paper(
    conn: sqlite3.Connection,
    paper_id: str = "p1",
    title: str = "Test Paper",
    authors: list[str] | None = None,
    abstract: str = "",
) -> None:
    conn.execute(
        """INSERT INTO papers (paper_id, title, authors, abstract, workflow_status)
           VALUES (?, ?, ?, ?, 'inbox')""",
        (paper_id, title, json.dumps(authors or []), abstract),
    )


def _insert_file_with_text(
    conn: sqlite3.Connection,
    file_id: str = "f1",
    paper_id: str = "p1",
    full_text: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO file_assets
           (file_id, paper_id, absolute_path, filename, full_text_extracted, full_text)
           VALUES (?, ?, '/tmp/test.pdf', 'test.pdf', ?, ?)""",
        (file_id, paper_id, 1 if full_text else 0, full_text),
    )


def _insert_markdown_note(
    conn: sqlite3.Connection,
    *,
    note_id: str = "n1",
    paper_id: str = "p1",
    location: str = "/tmp/p1.md",
    title: str = "Note Title",
) -> None:
    conn.execute(
        """INSERT INTO notes
           (note_id, paper_id, note_type, location, title)
           VALUES (?, ?, 'markdown_note', ?, ?)""",
        (note_id, paper_id, location, title),
    )


class TestRebuildSearchIndex:
    def test_empty_db(self, db_conn: sqlite3.Connection) -> None:
        report = rebuild_search_index(db_conn)
        assert report.papers_indexed == 0
        assert report.fulltext_indexed == 0

    def test_indexes_papers(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", "Alpha Paper", ["Author A"])
        _insert_paper(db_conn, "p2", "Beta Paper", ["Author B"])
        db_conn.commit()

        report = rebuild_search_index(db_conn)
        assert report.papers_indexed == 2

        rows = db_conn.execute("SELECT * FROM papers_fts").fetchall()
        assert len(rows) == 2

    def test_indexes_fulltext(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", "Paper One")
        _insert_file_with_text(db_conn, "f1", "p1", "Full text content here")
        db_conn.commit()

        report = rebuild_search_index(db_conn)
        assert report.fulltext_indexed == 1

    def test_skips_null_fulltext(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", "Paper One")
        _insert_file_with_text(db_conn, "f1", "p1", None)
        db_conn.commit()

        report = rebuild_search_index(db_conn)
        assert report.fulltext_indexed == 0

    def test_rebuild_clears_old_data(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", "Paper One")
        db_conn.commit()

        rebuild_search_index(db_conn)
        assert db_conn.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0] == 1

        # Delete the paper and rebuild — FTS should be empty
        db_conn.execute("DELETE FROM papers WHERE paper_id = 'p1'")
        db_conn.commit()
        report = rebuild_search_index(db_conn)
        assert report.papers_indexed == 0
        assert db_conn.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0] == 0

    def test_indexes_notes_from_note_files(
        self,
        db_conn: sqlite3.Connection,
        tmp_path: Path,
    ) -> None:
        _insert_paper(db_conn, "p1", "Paper One")
        note_path = tmp_path / "p1.md"
        note_path.write_text("# My Note\nGraph neural networks for molecules.")
        _insert_markdown_note(db_conn, paper_id="p1", location=str(note_path))
        db_conn.commit()

        report = rebuild_search_index(db_conn)
        assert report.notes_indexed == 1
        row = db_conn.execute(
            "SELECT note_content FROM notes_fts WHERE paper_id = 'p1'"
        ).fetchone()
        assert row is not None
        assert "Graph neural networks" in row[0]

    def test_missing_note_files_are_skipped_safely(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", "Paper One")
        _insert_markdown_note(db_conn, paper_id="p1", location="/tmp/does-not-exist.md")
        db_conn.commit()

        report = rebuild_search_index(db_conn)
        assert report.notes_indexed == 0
        count = db_conn.execute("SELECT COUNT(*) FROM notes_fts").fetchone()[0]
        assert count == 0

    def test_invalid_utf8_note_is_skipped_safely_on_rebuild(
        self,
        db_conn: sqlite3.Connection,
        tmp_path: Path,
    ) -> None:
        _insert_paper(db_conn, "p1", "Paper One")
        note_path = tmp_path / "invalid.md"
        note_path.write_bytes(b"\xff\xfe\xfd")
        _insert_markdown_note(db_conn, paper_id="p1", location=str(note_path))
        db_conn.commit()

        report = rebuild_search_index(db_conn)
        assert report.notes_indexed == 0
        count = db_conn.execute("SELECT COUNT(*) FROM notes_fts").fetchone()[0]
        assert count == 0


class TestIndexPaper:
    def test_incremental_index(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", "Incremental Paper", ["Auth"], "An abstract")
        _insert_file_with_text(db_conn, "f1", "p1", "Some full text")
        db_conn.commit()

        index_paper(db_conn, "p1")

        fts_row = db_conn.execute(
            "SELECT title FROM papers_fts WHERE paper_id = 'p1'"
        ).fetchone()
        assert fts_row[0] == "Incremental Paper"

        ft_row = db_conn.execute(
            "SELECT full_text FROM fulltext_fts WHERE paper_id = 'p1'"
        ).fetchone()
        assert ft_row[0] == "Some full text"

    def test_replaces_existing_entry(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1", "Original Title")
        db_conn.commit()
        index_paper(db_conn, "p1")

        # Update title and re-index
        db_conn.execute("UPDATE papers SET title = 'Updated Title' WHERE paper_id = 'p1'")
        db_conn.commit()
        index_paper(db_conn, "p1")

        rows = db_conn.execute("SELECT title FROM papers_fts WHERE paper_id = 'p1'").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Updated Title"

    def test_incremental_indexes_note_content(
        self,
        db_conn: sqlite3.Connection,
        tmp_path: Path,
    ) -> None:
        _insert_paper(db_conn, "p1", "Incremental Paper")
        note_path = tmp_path / "p1.md"
        note_path.write_text("# Note\nTransformer architecture details.")
        _insert_markdown_note(db_conn, paper_id="p1", location=str(note_path), title="Paper Note")
        db_conn.commit()

        index_paper(db_conn, "p1")
        row = db_conn.execute(
            "SELECT note_title, note_content FROM notes_fts WHERE paper_id = 'p1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Paper Note"
        assert "Transformer architecture" in row[1]

    def test_incremental_skips_invalid_utf8_note(
        self,
        db_conn: sqlite3.Connection,
        tmp_path: Path,
    ) -> None:
        _insert_paper(db_conn, "p1", "Incremental Paper")
        note_path = tmp_path / "bad.md"
        note_path.write_bytes(b"\xff\xfe\xfd")
        _insert_markdown_note(db_conn, paper_id="p1", location=str(note_path), title="Bad Note")
        db_conn.commit()

        index_paper(db_conn, "p1")
        row = db_conn.execute(
            "SELECT COUNT(*) FROM notes_fts WHERE paper_id = 'p1'"
        ).fetchone()
        assert row[0] == 0
