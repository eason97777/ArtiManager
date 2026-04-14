"""Tests for notes.manager module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from artimanager.notes.manager import (
    NoteRecord,
    create_note,
    get_note,
    init_note_from_template,
)


@pytest.fixture(autouse=True)
def _seed_paper(db_conn: sqlite3.Connection) -> None:
    """Ensure paper-1 exists for all tests."""
    db_conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title) VALUES ('paper-1', 'Test Paper')"
    )
    db_conn.commit()


def test_create_note(db_conn: sqlite3.Connection, tmp_path: Path) -> None:
    notes_root = tmp_path / "notes"
    record = create_note(db_conn, "paper-1", notes_root, title="My Note")

    assert isinstance(record, NoteRecord)
    assert record.paper_id == "paper-1"
    assert record.title == "My Note"
    assert record.note_type == "markdown_note"
    assert record.location.endswith("paper-1.md")
    assert Path(record.location).exists()

    row = db_conn.execute("SELECT COUNT(*) FROM notes WHERE paper_id = 'paper-1'").fetchone()
    assert row[0] == 1


def test_create_note_dedup(db_conn: sqlite3.Connection, tmp_path: Path) -> None:
    notes_root = tmp_path / "notes"
    first = create_note(db_conn, "paper-1", notes_root, title="First")
    second = create_note(db_conn, "paper-1", notes_root, title="Second")

    assert first.note_id == second.note_id
    assert first.title == "First"
    assert second.title == "First"


def test_init_note_from_template(db_conn: sqlite3.Connection, tmp_path: Path) -> None:
    notes_root = tmp_path / "notes"
    template = tmp_path / "template.md"
    template.write_text(
        '---\npaper_id: ""\ntitle: ""\ncreated_at: ""\nupdated_at: ""\n---\n# Notes\n'
    )

    record = init_note_from_template(db_conn, "paper-1", notes_root, title="Template Note",
                                     template_path=template)

    assert isinstance(record, NoteRecord)
    content = Path(record.location).read_text()
    assert 'paper_id: "paper-1"' in content
    assert 'title: "Template Note"' in content
    assert 'created_at: "' in content
    assert 'updated_at: "' in content


def test_init_note_from_template_default(db_conn: sqlite3.Connection, tmp_path: Path) -> None:
    """When no template_path is given, uses the bundled default template."""
    notes_root = tmp_path / "notes"
    record = init_note_from_template(db_conn, "paper-1", notes_root, title="Default Note")

    assert isinstance(record, NoteRecord)
    assert Path(record.location).exists()
    assert "template_version: v2" in Path(record.location).read_text()


def test_get_note(db_conn: sqlite3.Connection, tmp_path: Path) -> None:
    notes_root = tmp_path / "notes"
    create_note(db_conn, "paper-1", notes_root, title="My Note")

    record = get_note(db_conn, "paper-1")
    assert record is not None
    assert record.paper_id == "paper-1"
    assert record.title == "My Note"


def test_get_note_missing(db_conn: sqlite3.Connection) -> None:
    assert get_note(db_conn, "nonexistent") is None
