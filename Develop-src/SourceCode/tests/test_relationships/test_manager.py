"""Tests for relationships.manager module."""

from __future__ import annotations

import sqlite3

import pytest

from artimanager.relationships.manager import (
    RelationshipRecord,
    create_relationship,
    delete_relationship,
    get_relationships,
    update_relationship_status,
)


@pytest.fixture(autouse=True)
def _seed_papers(db_conn: sqlite3.Connection) -> None:
    """Ensure paper-1 and paper-2 exist for all tests."""
    db_conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title) VALUES ('paper-1', 'Test Paper 1')"
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title) VALUES ('paper-2', 'Test Paper 2')"
    )
    db_conn.commit()


# ---------------------------------------------------------------------------
# create_relationship
# ---------------------------------------------------------------------------


def test_create_relationship(db_conn: sqlite3.Connection) -> None:
    rec = create_relationship(db_conn, "paper-1", "paper-2", "cites")

    assert isinstance(rec, RelationshipRecord)
    assert rec.source_paper_id == "paper-1"
    assert rec.target_paper_id == "paper-2"
    assert rec.relationship_type == "cites"
    assert rec.status == "confirmed"
    assert rec.evidence_type == "user_asserted"
    assert rec.created_by == "user"
    assert rec.relationship_id  # non-empty
    assert rec.created_at  # non-empty

    row = db_conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE relationship_id = ?",
        (rec.relationship_id,),
    ).fetchone()
    assert row[0] == 1


def test_create_returns_existing_on_duplicate(db_conn: sqlite3.Connection) -> None:
    first = create_relationship(db_conn, "paper-1", "paper-2", "cites")
    second = create_relationship(db_conn, "paper-1", "paper-2", "cites")

    assert first.relationship_id == second.relationship_id

    row = db_conn.execute(
        "SELECT COUNT(*) FROM relationships "
        "WHERE source_paper_id = 'paper-1' AND target_paper_id = 'paper-2' "
        "AND relationship_type = 'cites'"
    ).fetchone()
    assert row[0] == 1


def test_prevent_self_reference(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Self-referencing"):
        create_relationship(db_conn, "paper-1", "paper-1", "cites")


# ---------------------------------------------------------------------------
# get_relationships
# ---------------------------------------------------------------------------


def test_get_relationships_outgoing(db_conn: sqlite3.Connection) -> None:
    create_relationship(db_conn, "paper-1", "paper-2", "cites")

    outgoing = get_relationships(db_conn, "paper-1", direction="outgoing")
    assert len(outgoing) == 1
    assert outgoing[0].source_paper_id == "paper-1"

    # paper-2 should have no outgoing relationships
    assert get_relationships(db_conn, "paper-2", direction="outgoing") == []


def test_get_relationships_incoming(db_conn: sqlite3.Connection) -> None:
    create_relationship(db_conn, "paper-1", "paper-2", "cites")

    incoming = get_relationships(db_conn, "paper-2", direction="incoming")
    assert len(incoming) == 1
    assert incoming[0].target_paper_id == "paper-2"

    # paper-1 should have no incoming relationships
    assert get_relationships(db_conn, "paper-1", direction="incoming") == []


def test_get_relationships_both(db_conn: sqlite3.Connection) -> None:
    # paper-3 for a second relationship where paper-1 is the target
    db_conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title) VALUES ('paper-3', 'Test Paper 3')"
    )
    db_conn.commit()

    create_relationship(db_conn, "paper-1", "paper-2", "cites")
    create_relationship(db_conn, "paper-3", "paper-1", "extends")

    both = get_relationships(db_conn, "paper-1", direction="both")
    assert len(both) == 2

    ids = {r.relationship_type for r in both}
    assert ids == {"cites", "extends"}


def test_get_relationships_empty(db_conn: sqlite3.Connection) -> None:
    result = get_relationships(db_conn, "paper-1")
    assert result == []


def test_get_relationships_status_filter(db_conn: sqlite3.Connection) -> None:
    create_relationship(
        db_conn, "paper-1", "paper-2", "cites", status="confirmed",
    )

    db_conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title) VALUES ('paper-3', 'Test Paper 3')"
    )
    db_conn.commit()
    create_relationship(
        db_conn, "paper-1", "paper-3", "extends", status="suggested",
    )

    confirmed = get_relationships(db_conn, "paper-1", status="confirmed")
    assert len(confirmed) == 1
    assert confirmed[0].relationship_type == "cites"

    suggested = get_relationships(db_conn, "paper-1", status="suggested")
    assert len(suggested) == 1
    assert suggested[0].relationship_type == "extends"


# ---------------------------------------------------------------------------
# update_relationship_status
# ---------------------------------------------------------------------------


def test_update_status_suggested_to_confirmed(db_conn: sqlite3.Connection) -> None:
    rec = create_relationship(
        db_conn, "paper-1", "paper-2", "cites", status="suggested",
    )

    update_relationship_status(db_conn, rec.relationship_id, "confirmed")

    row = db_conn.execute(
        "SELECT status FROM relationships WHERE relationship_id = ?",
        (rec.relationship_id,),
    ).fetchone()
    assert row[0] == "confirmed"


def test_update_status_invalid_transition(db_conn: sqlite3.Connection) -> None:
    rec = create_relationship(
        db_conn, "paper-1", "paper-2", "cites", status="confirmed",
    )

    with pytest.raises(ValueError, match="Invalid status transition"):
        update_relationship_status(db_conn, rec.relationship_id, "suggested")


# ---------------------------------------------------------------------------
# delete_relationship
# ---------------------------------------------------------------------------


def test_delete_user_asserted(db_conn: sqlite3.Connection) -> None:
    rec = create_relationship(
        db_conn, "paper-1", "paper-2", "cites", evidence_type="user_asserted",
    )

    delete_relationship(db_conn, rec.relationship_id)

    row = db_conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE relationship_id = ?",
        (rec.relationship_id,),
    ).fetchone()
    assert row[0] == 0


def test_delete_non_user_asserted_fails(db_conn: sqlite3.Connection) -> None:
    rec = create_relationship(
        db_conn, "paper-1", "paper-2", "cites", evidence_type="citation_based",
    )

    with pytest.raises(ValueError, match="Cannot delete"):
        delete_relationship(db_conn, rec.relationship_id)
