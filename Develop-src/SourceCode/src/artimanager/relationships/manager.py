"""Relationship management — create, query, update, and delete paper relationships."""

from __future__ import annotations

from dataclasses import dataclass

from artimanager.db.utils import new_id, now_iso


# ---------------------------------------------------------------------------
# Valid status transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "suggested": {"confirmed", "rejected"},
}


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class RelationshipRecord:
    """A directed relationship between two papers."""

    relationship_id: str
    source_paper_id: str
    target_paper_id: str
    relationship_type: str
    status: str
    evidence_type: str | None
    evidence_text: str | None
    confidence: float | None
    created_by: str | None
    created_at: str


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

_SELECT_COLS = (
    "relationship_id, source_paper_id, target_paper_id, relationship_type, "
    "status, evidence_type, evidence_text, confidence, created_by, created_at"
)


def _row_to_record(row) -> RelationshipRecord:
    return RelationshipRecord(*row)


def create_relationship(
    conn,
    source_paper_id: str,
    target_paper_id: str,
    relationship_type: str,
    *,
    evidence_type: str = "user_asserted",
    evidence_text: str | None = None,
    confidence: float | None = None,
    created_by: str = "user",
    status: str = "confirmed",
) -> RelationshipRecord:
    """Create a relationship between two papers.

    Raises ``ValueError`` if *source_paper_id* equals *target_paper_id*.
    Returns the existing record when a duplicate
    ``(source_paper_id, target_paper_id, relationship_type)`` is found.
    """
    if source_paper_id == target_paper_id:
        raise ValueError("Self-referencing relationship is not allowed")

    # Duplicate check
    row = conn.execute(
        f"SELECT {_SELECT_COLS} FROM relationships "
        "WHERE source_paper_id = ? AND target_paper_id = ? AND relationship_type = ?",
        (source_paper_id, target_paper_id, relationship_type),
    ).fetchone()
    if row is not None:
        return _row_to_record(row)

    now = now_iso()
    rid = new_id()
    conn.execute(
        """INSERT INTO relationships
           (relationship_id, source_paper_id, target_paper_id, relationship_type,
            status, evidence_type, evidence_text, confidence, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (rid, source_paper_id, target_paper_id, relationship_type,
         status, evidence_type, evidence_text, confidence, created_by, now),
    )
    return RelationshipRecord(
        relationship_id=rid,
        source_paper_id=source_paper_id,
        target_paper_id=target_paper_id,
        relationship_type=relationship_type,
        status=status,
        evidence_type=evidence_type,
        evidence_text=evidence_text,
        confidence=confidence,
        created_by=created_by,
        created_at=now,
    )


def get_relationship(conn, relationship_id: str) -> RelationshipRecord | None:
    """Return one relationship by ID."""
    row = conn.execute(
        f"SELECT {_SELECT_COLS} FROM relationships WHERE relationship_id = ?",
        (relationship_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_relationships(
    conn,
    *,
    paper_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[RelationshipRecord]:
    """List relationships for review queues with optional filters."""
    clauses: list[str] = []
    params: list = []
    if paper_id:
        clauses.append("(source_paper_id = ? OR target_paper_id = ?)")
        params.extend([paper_id, paper_id])
    if status:
        clauses.append("status = ?")
        params.append(status)

    sql = f"SELECT {_SELECT_COLS} FROM relationships"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(r) for r in rows]


def get_relationships(
    conn,
    paper_id: str,
    *,
    direction: str = "both",
    status: str | None = None,
) -> list[RelationshipRecord]:
    """Return relationships linked to *paper_id*.

    *direction* controls which side of the edge to match:
    ``"outgoing"`` (source), ``"incoming"`` (target), or ``"both"``.
    *status* optionally filters by relationship status.
    """
    clauses: list[str] = []
    params: list[str] = []

    if direction == "outgoing":
        clauses.append("source_paper_id = ?")
        params.append(paper_id)
    elif direction == "incoming":
        clauses.append("target_paper_id = ?")
        params.append(paper_id)
    else:  # both
        clauses.append("(source_paper_id = ? OR target_paper_id = ?)")
        params.extend([paper_id, paper_id])

    if status is not None:
        clauses.append("status = ?")
        params.append(status)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT {_SELECT_COLS} FROM relationships WHERE {where}",
        params,
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def update_relationship_status(
    conn,
    relationship_id: str,
    new_status: str,
) -> None:
    """Transition a relationship to *new_status*.

    Only transitions defined in ``_VALID_TRANSITIONS`` are allowed.
    Raises ``ValueError`` for any other transition.
    """
    row = conn.execute(
        "SELECT status FROM relationships WHERE relationship_id = ?",
        (relationship_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Relationship {relationship_id!r} not found")

    current_status = row[0]
    allowed = _VALID_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Invalid status transition: {current_status!r} -> {new_status!r}"
        )

    conn.execute(
        "UPDATE relationships SET status = ? WHERE relationship_id = ?",
        (new_status, relationship_id),
    )


def delete_relationship(conn, relationship_id: str) -> None:
    """Delete a relationship.

    Only relationships with ``evidence_type='user_asserted'`` may be deleted.
    Raises ``ValueError`` otherwise.
    """
    row = conn.execute(
        "SELECT evidence_type FROM relationships WHERE relationship_id = ?",
        (relationship_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Relationship {relationship_id!r} not found")

    if row[0] != "user_asserted":
        raise ValueError(
            f"Cannot delete relationship with evidence_type={row[0]!r}; "
            "only 'user_asserted' relationships may be deleted"
        )

    conn.execute(
        "DELETE FROM relationships WHERE relationship_id = ?",
        (relationship_id,),
    )
