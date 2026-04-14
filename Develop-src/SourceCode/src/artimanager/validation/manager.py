"""Validation record management — track reproduction/experiment attempts."""

from __future__ import annotations

from dataclasses import dataclass

from artimanager.db.utils import new_id, now_iso


@dataclass
class ValidationRecord:
    """A validation/experiment record for a paper."""

    validation_id: str
    paper_id: str
    path: str | None
    repo_url: str | None
    environment_note: str | None
    outcome: str  # "not_attempted" | "in_progress" | "reproduced" | "partially_reproduced" | "failed"
    summary: str | None
    updated_at: str


def create_validation(
    conn,
    paper_id: str,
    *,
    path: str | None = None,
    repo_url: str | None = None,
    environment_note: str | None = None,
) -> ValidationRecord:
    """Create a validation record for a paper."""
    now = now_iso()
    vid = new_id()
    conn.execute(
        """INSERT INTO validation_records
           (validation_id, paper_id, path, repo_url, environment_note, outcome, summary, updated_at)
           VALUES (?, ?, ?, ?, ?, 'not_attempted', ?, ?)""",
        (vid, paper_id, path, repo_url, environment_note, None, now),
    )
    return ValidationRecord(
        validation_id=vid,
        paper_id=paper_id,
        path=path,
        repo_url=repo_url,
        environment_note=environment_note,
        outcome="not_attempted",
        summary=None,
        updated_at=now,
    )


def update_validation_outcome(
    conn,
    validation_id: str,
    outcome: str,
    *,
    summary: str | None = None,
) -> None:
    """Update the outcome of a validation record."""
    now = now_iso()
    if summary is not None:
        conn.execute(
            "UPDATE validation_records SET outcome = ?, summary = ?, updated_at = ? "
            "WHERE validation_id = ?",
            (outcome, summary, now, validation_id),
        )
    else:
        conn.execute(
            "UPDATE validation_records SET outcome = ?, updated_at = ? "
            "WHERE validation_id = ?",
            (outcome, now, validation_id),
        )


def get_validations(conn, paper_id: str) -> list[ValidationRecord]:
    """Return all validation records for a paper."""
    rows = conn.execute(
        "SELECT validation_id, paper_id, path, repo_url, environment_note, "
        "outcome, summary, updated_at "
        "FROM validation_records WHERE paper_id = ?",
        (paper_id,),
    ).fetchall()
    return [ValidationRecord(*r) for r in rows]
