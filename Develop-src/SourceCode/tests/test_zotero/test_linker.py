"""Tests for zotero.linker module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from artimanager.zotero._models import ZoteroItem
from artimanager.zotero.linker import (
    ZoteroLink,
    find_paper_by_zotero_key,
    get_zotero_link,
    link_paper_to_zotero,
    sync_paper_metadata,
)


@pytest.fixture(autouse=True)
def _seed_paper(db_conn: sqlite3.Connection) -> None:
    """Ensure paper-1 exists for all tests."""
    db_conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title) VALUES ('paper-1', 'Test Paper')"
    )
    db_conn.commit()


def test_link_paper(db_conn: sqlite3.Connection) -> None:
    link = link_paper_to_zotero(db_conn, "paper-1", "ABC123", "12345")
    assert isinstance(link, ZoteroLink)
    assert link.paper_id == "paper-1"
    assert link.zotero_item_key == "ABC123"
    assert link.zotero_library_id == "12345"

    row = db_conn.execute(
        "SELECT zotero_item_key FROM zotero_links WHERE paper_id = 'paper-1'"
    ).fetchone()
    assert row[0] == "ABC123"

    row = db_conn.execute(
        "SELECT zotero_item_key FROM papers WHERE paper_id = 'paper-1'"
    ).fetchone()
    assert row[0] == "ABC123"


def test_link_upsert(db_conn: sqlite3.Connection) -> None:
    link1 = link_paper_to_zotero(db_conn, "paper-1", "ABC123", "12345")
    link2 = link_paper_to_zotero(db_conn, "paper-1", "DEF456", "12345")
    assert link1.paper_id == link2.paper_id
    assert link2.zotero_item_key == "DEF456"

    count = db_conn.execute("SELECT COUNT(*) FROM zotero_links WHERE paper_id = 'paper-1'").fetchone()
    assert count[0] == 1


def test_get_zotero_link(db_conn: sqlite3.Connection) -> None:
    link_paper_to_zotero(db_conn, "paper-1", "ABC123", "12345")
    link = get_zotero_link(db_conn, "paper-1")
    assert link is not None
    assert link.zotero_item_key == "ABC123"


def test_get_zotero_link_missing(db_conn: sqlite3.Connection) -> None:
    assert get_zotero_link(db_conn, "paper-1") is None


def test_find_paper_by_zotero_key(db_conn: sqlite3.Connection) -> None:
    link_paper_to_zotero(db_conn, "paper-1", "ABC123", "12345")
    pid = find_paper_by_zotero_key(db_conn, "ABC123")
    assert pid == "paper-1"


def test_find_paper_by_zotero_key_missing(db_conn: sqlite3.Connection) -> None:
    assert find_paper_by_zotero_key(db_conn, "NONEXISTENT") is None


def test_sync_metadata_fills_blanks(db_conn: sqlite3.Connection) -> None:
    db_conn.execute("UPDATE papers SET title = NULL WHERE paper_id = 'paper-1'")
    db_conn.commit()

    item = ZoteroItem(
        key="ABC123",
        item_type="journalArticle",
        title="Real Title",
        creators=[{"firstName": "Jane", "lastName": "Doe", "creatorType": "author"}],
        date="2024-03-15",
        doi="10.1234/test",
        arxiv_id="2403.00001",
        abstract="An abstract.",
    )
    diff = sync_paper_metadata(db_conn, "paper-1", item)
    assert "title" in diff
    assert "doi" in diff
    assert "arxiv_id" in diff
    assert "abstract" in diff
    assert "year" in diff
    assert diff["title"] == (None, "Real Title")

    row = db_conn.execute(
        "SELECT title, doi, arxiv_id, year FROM papers WHERE paper_id = 'paper-1'"
    ).fetchone()
    assert row[0] == "Real Title"
    assert row[1] == "10.1234/test"
    assert row[2] == "2403.00001"
    assert row[3] == 2024


def test_sync_metadata_no_overwrite(db_conn: sqlite3.Connection) -> None:
    db_conn.execute(
        "UPDATE papers SET title = 'Existing Title', doi = '10.9999/old' WHERE paper_id = 'paper-1'"
    )
    db_conn.commit()

    item = ZoteroItem(
        key="ABC123",
        item_type="journalArticle",
        title="New Title",
        creators=[],
        doi="10.1234/new",
    )
    diff = sync_paper_metadata(db_conn, "paper-1", item)
    assert "title" not in diff
    assert "doi" not in diff

    row = db_conn.execute(
        "SELECT title, doi FROM papers WHERE paper_id = 'paper-1'"
    ).fetchone()
    assert row[0] == "Existing Title"
    assert row[1] == "10.9999/old"


def test_sync_metadata_partial_fill(db_conn: sqlite3.Connection) -> None:
    db_conn.execute(
        "UPDATE papers SET title = 'Has Title' WHERE paper_id = 'paper-1'"
    )
    db_conn.commit()

    item = ZoteroItem(
        key="ABC123",
        item_type="journalArticle",
        title="Different Title",
        creators=[],
        doi="10.1234/test",
    )
    diff = sync_paper_metadata(db_conn, "paper-1", item)
    assert "title" not in diff
    assert "doi" in diff


def test_sync_metadata_paper_missing(db_conn: sqlite3.Connection) -> None:
    item = ZoteroItem(key="X", item_type="book", title="T", creators=[])
    with pytest.raises(ValueError, match="not found"):
        sync_paper_metadata(db_conn, "nonexistent", item)
