"""Tests for validation.manager module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from artimanager.validation.manager import (
    ValidationRecord,
    create_validation,
    get_validations,
    update_validation_outcome,
)


@pytest.fixture(autouse=True)
def _seed_paper(db_conn: sqlite3.Connection) -> None:
    """Ensure paper-1 exists for all tests."""
    db_conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title) VALUES ('paper-1', 'Test Paper')"
    )
    db_conn.commit()


def test_create_validation(db_conn: sqlite3.Connection) -> None:
    record = create_validation(db_conn, "paper-1")

    assert isinstance(record, ValidationRecord)
    assert record.paper_id == "paper-1"
    assert record.outcome == "not_attempted"
    assert record.summary is None
    assert record.path is None
    assert record.repo_url is None

    row = db_conn.execute(
        "SELECT COUNT(*) FROM validation_records WHERE paper_id = 'paper-1'"
    ).fetchone()
    assert row[0] == 1


def test_create_validation_with_fields(db_conn: sqlite3.Connection) -> None:
    record = create_validation(
        db_conn, "paper-1",
        path="/tmp/workspace",
        repo_url="https://github.com/example/repo",
        environment_note="Python 3.11, CUDA 12",
    )

    assert record.path == "/tmp/workspace"
    assert record.repo_url == "https://github.com/example/repo"
    assert record.environment_note == "Python 3.11, CUDA 12"


def test_update_validation_outcome(db_conn: sqlite3.Connection) -> None:
    record = create_validation(db_conn, "paper-1")
    update_validation_outcome(db_conn, record.validation_id, "reproduced",
                              summary="All tests passed")

    row = db_conn.execute(
        "SELECT outcome, summary FROM validation_records WHERE validation_id = ?",
        (record.validation_id,),
    ).fetchone()
    assert row[0] == "reproduced"
    assert row[1] == "All tests passed"


def test_update_validation_outcome_no_summary(db_conn: sqlite3.Connection) -> None:
    record = create_validation(db_conn, "paper-1")
    update_validation_outcome(db_conn, record.validation_id, "failed")

    row = db_conn.execute(
        "SELECT outcome, summary FROM validation_records WHERE validation_id = ?",
        (record.validation_id,),
    ).fetchone()
    assert row[0] == "failed"
    assert row[1] is None


def test_get_validations(db_conn: sqlite3.Connection) -> None:
    create_validation(db_conn, "paper-1")
    create_validation(db_conn, "paper-1")

    validations = get_validations(db_conn, "paper-1")
    assert len(validations) == 2
    assert all(v.paper_id == "paper-1" for v in validations)


def test_get_validations_empty(db_conn: sqlite3.Connection) -> None:
    validations = get_validations(db_conn, "paper-1")
    assert validations == []
