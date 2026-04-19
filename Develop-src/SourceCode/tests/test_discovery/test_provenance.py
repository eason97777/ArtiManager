"""Tests for discovery provenance storage."""

from __future__ import annotations

import sqlite3

import pytest

from artimanager.discovery.engine import DiscoveryRecord, store_discovery_record
from artimanager.discovery.provenance import (
    DiscoverySourceContext,
    build_provenance_key,
    store_discovery_record_with_source,
)


def _record(
    *,
    result_id: str = "r1",
    source: str = "semantic_scholar",
    external_id: str = "S2-1",
    doi: str | None = "10.1000/one",
    arxiv_id: str | None = None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        discovery_result_id=result_id,
        trigger_type="topic_anchor",
        trigger_ref="graph",
        source=source,
        external_id=external_id,
        title="Candidate",
        authors=["A"],
        abstract="Abstract",
        doi=doi,
        arxiv_id=arxiv_id,
        published_at="2026",
        relevance_score=0.7,
        relevance_context="context",
    )


def _context(
    *,
    trigger_ref: str = "graph",
    source: str = "semantic_scholar",
    source_external_id: str = "S2-1",
    tracking_rule_id: str | None = None,
) -> DiscoverySourceContext:
    return DiscoverySourceContext(
        trigger_type="tracking_rule" if tracking_rule_id else "topic_anchor",
        trigger_ref=tracking_rule_id or trigger_ref,
        tracking_rule_id=tracking_rule_id,
        source=source,
        source_external_id=source_external_id,
        relevance_score=0.7,
        relevance_context="context",
    )


def test_build_provenance_key_is_deterministic_and_ignores_context_text() -> None:
    context = _context()
    changed_text = DiscoverySourceContext(
        trigger_type=context.trigger_type,
        trigger_ref=context.trigger_ref,
        source=context.source,
        source_external_id=context.source_external_id,
        relevance_score=0.1,
        relevance_context="different summary text",
    )

    assert build_provenance_key(context) == build_provenance_key(context)
    assert build_provenance_key(context) == build_provenance_key(changed_text)


def test_store_inserts_candidate_and_provenance(db_conn: sqlite3.Connection) -> None:
    outcome = store_discovery_record_with_source(db_conn, _record(), _context())

    assert outcome.candidate_inserted is True
    assert outcome.provenance_inserted is True
    candidate_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert candidate_count == 1
    assert source_count == 1


def test_repeated_same_trigger_is_idempotent(db_conn: sqlite3.Connection) -> None:
    first = store_discovery_record_with_source(db_conn, _record(), _context())
    second = store_discovery_record_with_source(
        db_conn,
        _record(result_id="r2"),
        _context(),
    )

    assert first.candidate_inserted is True
    assert first.provenance_inserted is True
    assert second.candidate_inserted is False
    assert second.provenance_inserted is False
    candidate_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert candidate_count == 1
    assert source_count == 1


def test_same_candidate_from_two_triggers_keeps_two_provenance_rows(
    db_conn: sqlite3.Connection,
) -> None:
    first = store_discovery_record_with_source(db_conn, _record(), _context())
    second = store_discovery_record_with_source(
        db_conn,
        _record(result_id="r2"),
        _context(trigger_ref="graph neural nets"),
    )

    assert first.discovery_result_id == second.discovery_result_id
    assert second.candidate_inserted is False
    assert second.provenance_inserted is True
    candidate_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert candidate_count == 1
    assert source_count == 2


def test_provenance_failure_rolls_back_new_candidate(db_conn: sqlite3.Connection) -> None:
    record = _record(result_id="r-fail", doi="10.1000/fail", external_id="S2-fail")
    context = _context(tracking_rule_id="missing-rule", source_external_id="S2-fail")

    with pytest.raises(sqlite3.IntegrityError):
        store_discovery_record_with_source(db_conn, record, context)

    candidate_count = db_conn.execute(
        "SELECT COUNT(*) FROM discovery_results WHERE discovery_result_id = 'r-fail'"
    ).fetchone()[0]
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert candidate_count == 0
    assert source_count == 0


def test_store_discovery_record_backward_compatible(db_conn: sqlite3.Connection) -> None:
    inserted = store_discovery_record(db_conn, _record())
    duplicate = store_discovery_record(db_conn, _record(result_id="r2"))

    assert inserted is True
    assert duplicate is False
    candidate_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert candidate_count == 1
    assert source_count == 1
