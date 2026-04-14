"""Tests for relationships.suggest module."""

from __future__ import annotations

import sqlite3

import pytest

from artimanager.relationships.manager import (
    RelationshipRecord,
    create_relationship,
)
from artimanager.relationships.suggest import suggest_relationships


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_paper(
    conn: sqlite3.Connection,
    paper_id: str,
    title: str = "Test Paper",
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    year: int | None = None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO papers (paper_id, title, doi, arxiv_id, year) "
        "VALUES (?, ?, ?, ?, ?)",
        (paper_id, title, doi, arxiv_id, year),
    )
    conn.commit()


def _insert_discovery_result(
    conn: sqlite3.Connection,
    *,
    result_id: str = "dr-1",
    trigger_type: str = "paper_anchor",
    trigger_ref: str = "paper-1",
    status: str = "imported",
    imported_paper_id: str | None = "paper-2",
) -> None:
    conn.execute(
        "INSERT INTO discovery_results "
        "(discovery_result_id, trigger_type, trigger_ref, source, external_id, "
        " status, imported_paper_id) "
        "VALUES (?, ?, ?, 'semantic_scholar', ?, ?, ?)",
        (result_id, trigger_type, trigger_ref, result_id, status, imported_paper_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Strategy 1: citation-based (discovery_results)
# ---------------------------------------------------------------------------


def test_suggest_from_discovery_import(db_conn: sqlite3.Connection) -> None:
    _insert_paper(db_conn, "paper-1", "Paper One")
    _insert_paper(db_conn, "paper-2", "Paper Two")
    _insert_discovery_result(
        db_conn,
        trigger_type="paper_anchor",
        trigger_ref="paper-1",
        status="imported",
        imported_paper_id="paper-2",
    )

    suggestions = suggest_relationships(db_conn, "paper-1")

    assert len(suggestions) == 1
    rec = suggestions[0]
    assert isinstance(rec, RelationshipRecord)
    assert rec.source_paper_id == "paper-1"
    assert rec.target_paper_id == "paper-2"
    assert rec.evidence_type == "citation_based"
    assert rec.status == "suggested"
    assert rec.created_by == "suggest_pipeline"


# ---------------------------------------------------------------------------
# Strategy 2: shared identifiers
# ---------------------------------------------------------------------------


def test_suggest_shared_doi_prefix(db_conn: sqlite3.Connection) -> None:
    _insert_paper(db_conn, "paper-1", "Paper One", doi="10.1234/abc")
    _insert_paper(db_conn, "paper-2", "Paper Two", doi="10.1234/xyz")

    suggestions = suggest_relationships(db_conn, "paper-1")

    assert len(suggestions) == 1
    rec = suggestions[0]
    assert rec.evidence_type == "metadata_match"
    assert rec.status == "suggested"


def test_suggest_shared_arxiv_prefix(db_conn: sqlite3.Connection) -> None:
    _insert_paper(db_conn, "paper-1", "Paper One", arxiv_id="2401.00001")
    _insert_paper(db_conn, "paper-2", "Paper Two", arxiv_id="2401.00999")

    suggestions = suggest_relationships(db_conn, "paper-1")

    assert len(suggestions) == 1
    rec = suggestions[0]
    assert rec.evidence_type == "metadata_match"
    assert rec.status == "suggested"


# ---------------------------------------------------------------------------
# Strategy 3: title similarity
# ---------------------------------------------------------------------------


def test_suggest_title_similarity(db_conn: sqlite3.Connection) -> None:
    _insert_paper(db_conn, "paper-1", "Deep Learning Methods for NLP Tasks")
    _insert_paper(db_conn, "paper-2", "Deep Learning Methods for NLP Applications")

    suggestions = suggest_relationships(db_conn, "paper-1")

    assert len(suggestions) == 1
    rec = suggestions[0]
    assert rec.evidence_type == "metadata_match"
    assert rec.status == "suggested"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_suggest_skips_existing_relationships(db_conn: sqlite3.Connection) -> None:
    _insert_paper(db_conn, "paper-1", "Paper One", doi="10.1234/abc")
    _insert_paper(db_conn, "paper-2", "Paper Two", doi="10.1234/xyz")

    # Pre-create a relationship so the suggestion pipeline should skip it
    create_relationship(db_conn, "paper-1", "paper-2", "cites")

    suggestions = suggest_relationships(db_conn, "paper-1")
    assert suggestions == []


def test_suggest_empty_for_isolated_paper(db_conn: sqlite3.Connection) -> None:
    _insert_paper(db_conn, "paper-1", "Completely Unique Unrelated Title XYZ123")

    suggestions = suggest_relationships(db_conn, "paper-1")
    assert suggestions == []


def test_suggest_no_self_reference(db_conn: sqlite3.Connection) -> None:
    _insert_paper(db_conn, "paper-1", "Some Paper", doi="10.1234/abc")

    # Insert a discovery result that points back to the same paper
    _insert_discovery_result(
        db_conn,
        trigger_type="paper_anchor",
        trigger_ref="paper-1",
        status="imported",
        imported_paper_id="paper-1",
    )

    suggestions = suggest_relationships(db_conn, "paper-1")
    # Should be empty — self-references are skipped
    assert suggestions == []
