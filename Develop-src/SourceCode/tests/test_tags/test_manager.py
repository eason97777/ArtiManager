"""Tests for tags.manager."""

from __future__ import annotations

import sqlite3

import pytest

from artimanager.tags.manager import add_tag_to_paper, list_tags_for_paper, remove_tag_from_paper


@pytest.fixture(autouse=True)
def _seed_paper(db_conn: sqlite3.Connection) -> None:
    db_conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title) VALUES ('p1', 'Paper 1')"
    )
    db_conn.commit()


def test_add_tag_creates_tag_and_link(db_conn: sqlite3.Connection) -> None:
    tag = add_tag_to_paper(db_conn, "p1", "Graph ML", tag_type="topic")
    db_conn.commit()
    assert tag.name == "Graph ML"
    assert tag.tag_type == "topic"

    row = db_conn.execute(
        """SELECT t.name, t.tag_type, pt.confirmed_by_user
           FROM paper_tags pt
           JOIN tags t ON t.tag_id = pt.tag_id
           WHERE pt.paper_id = 'p1'"""
    ).fetchone()
    assert tuple(row) == ("Graph ML", "topic", 1)


def test_add_tag_normalizes_and_reuses_existing_case_insensitive(db_conn: sqlite3.Connection) -> None:
    first = add_tag_to_paper(db_conn, "p1", "Graph ML")
    second = add_tag_to_paper(db_conn, "p1", "  graph   ml  ")
    db_conn.commit()
    assert first.tag_id == second.tag_id

    rows = db_conn.execute("SELECT COUNT(*) FROM tags").fetchone()
    assert rows[0] == 1


def test_remove_tag_from_paper(db_conn: sqlite3.Connection) -> None:
    add_tag_to_paper(db_conn, "p1", "Graph ML")
    db_conn.commit()
    removed = remove_tag_from_paper(db_conn, "p1", " graph ml ")
    db_conn.commit()
    assert removed is True

    row = db_conn.execute("SELECT COUNT(*) FROM paper_tags WHERE paper_id = 'p1'").fetchone()
    assert row[0] == 0


def test_list_tags_for_paper(db_conn: sqlite3.Connection) -> None:
    add_tag_to_paper(db_conn, "p1", "NLP", tag_type="topic")
    add_tag_to_paper(db_conn, "p1", "Survey")
    db_conn.commit()

    tags = list_tags_for_paper(db_conn, "p1")
    assert [t.name for t in tags] == ["NLP", "Survey"]
