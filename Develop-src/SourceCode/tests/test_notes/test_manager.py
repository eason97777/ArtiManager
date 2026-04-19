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
    safe_markdown_filename,
    update_markdown_note_metadata,
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


def test_create_note_with_custom_safe_filename(
    db_conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    notes_root = tmp_path / "notes"
    record = create_note(
        db_conn,
        "paper-1",
        notes_root,
        title="My Note",
        filename="reading-note",
    )

    assert Path(record.location) == notes_root / "reading-note.md"
    assert Path(record.location).exists()


def test_create_note_dedup(db_conn: sqlite3.Connection, tmp_path: Path) -> None:
    notes_root = tmp_path / "notes"
    first = create_note(db_conn, "paper-1", notes_root, title="First")
    second = create_note(db_conn, "paper-1", notes_root, title="Second")

    assert first.note_id == second.note_id
    assert first.title == "First"
    assert second.title == "First"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "/tmp/note.md",
        ".hidden.md",
        ".",
        "nested/note.md",
        r"nested\note.md",
        "../note.md",
        "note..draft.md",
        "notebook.ipynb",
    ],
)
def test_safe_markdown_filename_rejects_unsafe_names(raw: str) -> None:
    with pytest.raises(ValueError):
        safe_markdown_filename(raw, "paper-1")


def test_safe_markdown_filename_defaults_and_appends_extension() -> None:
    assert safe_markdown_filename(None, "paper-1") == "paper-1.md"
    assert safe_markdown_filename("reading-note", "paper-1") == "reading-note.md"
    assert safe_markdown_filename("reading-note.md", "paper-1") == "reading-note.md"


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


def test_update_markdown_note_metadata_updates_title_and_renames_file(
    db_conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    notes_root = tmp_path / "notes"
    record = create_note(db_conn, "paper-1", notes_root, title="Old", filename="old.md")
    old_path = Path(record.location)
    old_path.write_text("# User-authored body\n", encoding="utf-8")

    updated = update_markdown_note_metadata(
        db_conn,
        "paper-1",
        record.note_id,
        notes_root,
        title="New Title",
        filename="renamed",
    )

    new_path = notes_root / "renamed.md"
    assert updated.title == "New Title"
    assert Path(updated.location) == new_path
    assert not old_path.exists()
    assert new_path.read_text(encoding="utf-8") == "# User-authored body\n"
    row = db_conn.execute(
        "SELECT title, location FROM notes WHERE note_id = ?",
        (record.note_id,),
    ).fetchone()
    assert row["title"] == "New Title"
    assert row["location"] == str(new_path)


def test_update_markdown_note_metadata_rejects_overwrite(
    db_conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    notes_root = tmp_path / "notes"
    record = create_note(db_conn, "paper-1", notes_root, title="Old", filename="old.md")
    target = notes_root / "taken.md"
    target.write_text("# Existing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        update_markdown_note_metadata(
            db_conn,
            "paper-1",
            record.note_id,
            notes_root,
            filename="taken.md",
        )

    assert Path(record.location).exists()
    assert target.read_text(encoding="utf-8") == "# Existing\n"


def test_update_markdown_note_metadata_rejects_missing_current_file_on_rename(
    db_conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    notes_root = tmp_path / "notes"
    record = create_note(db_conn, "paper-1", notes_root, title="Old", filename="old.md")
    Path(record.location).unlink()

    with pytest.raises(ValueError, match="does not exist"):
        update_markdown_note_metadata(
            db_conn,
            "paper-1",
            record.note_id,
            notes_root,
            filename="renamed.md",
        )
