"""Tests for shared paper update rules."""

from __future__ import annotations

import json
import sqlite3

import pytest

from artimanager.papers.manager import update_paper_metadata, update_paper_state


@pytest.fixture(autouse=True)
def _seed_paper(db_conn: sqlite3.Connection) -> None:
    db_conn.execute(
        """
        INSERT OR IGNORE INTO papers
        (paper_id, title, authors, workflow_status, reading_state, research_state)
        VALUES ('paper-1', 'Original', '[]', 'inbox', 'to_read', 'untriaged')
        """
    )
    db_conn.commit()


def test_update_paper_state_validates_and_persists(db_conn: sqlite3.Connection) -> None:
    changed = update_paper_state(
        db_conn,
        "paper-1",
        workflow_status="active",
        reading_state="read",
        research_state="relevant",
    )

    assert changed == {
        "workflow_status": "active",
        "reading_state": "read",
        "research_state": "relevant",
    }
    row = db_conn.execute(
        "SELECT workflow_status, reading_state, research_state, updated_at FROM papers WHERE paper_id = 'paper-1'"
    ).fetchone()
    assert row["workflow_status"] == "active"
    assert row["reading_state"] == "read"
    assert row["research_state"] == "relevant"
    assert row["updated_at"] is not None


def test_update_paper_state_rejects_invalid_value(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Invalid workflow_status"):
        update_paper_state(db_conn, "paper-1", workflow_status="random")


def test_update_paper_metadata_normalizes_allowed_fields(db_conn: sqlite3.Connection) -> None:
    update_paper_metadata(
        db_conn,
        "paper-1",
        title="  Corrected   Title ",
        authors="Alice Example; Bob Example",
        year="2026",
        doi=" 10.1234/example ",
        arxiv_id=" 2601.00001 ",
        abstract="Line one\n\n\nLine two",
    )

    row = db_conn.execute(
        "SELECT title, authors, year, doi, arxiv_id, abstract FROM papers WHERE paper_id = 'paper-1'"
    ).fetchone()
    assert row["title"] == "Corrected Title"
    assert json.loads(row["authors"]) == ["Alice Example", "Bob Example"]
    assert row["year"] == 2026
    assert row["doi"] == "10.1234/example"
    assert row["arxiv_id"] == "2601.00001"
    assert row["abstract"] == "Line one\n\nLine two"


def test_update_paper_metadata_rejects_unknown_paper(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Paper not found"):
        update_paper_metadata(db_conn, "missing", title="Title")
