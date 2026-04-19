"""Tests for tracking.manager."""

from __future__ import annotations

import sqlite3
import json

import pytest

from artimanager.tracking.manager import (
    create_tracking_rule,
    delete_tracking_rule,
    get_tracking_rule,
    list_tracking_rules,
    serialize_openalex_author_tracking_query,
    serialize_citation_tracking_query,
    update_tracking_rule,
)


def test_create_tracking_rule(db_conn: sqlite3.Connection) -> None:
    rule = create_tracking_rule(
        db_conn,
        name="NLP updates",
        rule_type="keyword",
        query="transformer",
        schedule="daily",
    )
    assert rule.name == "NLP updates"
    assert rule.rule_type == "keyword"
    assert rule.query == "transformer"
    assert rule.enabled is True


def test_get_and_list_rules(db_conn: sqlite3.Connection) -> None:
    rule = create_tracking_rule(
        db_conn, name="A", rule_type="topic", query="vision"
    )
    fetched = get_tracking_rule(db_conn, rule.tracking_rule_id)
    assert fetched is not None
    assert fetched.tracking_rule_id == rule.tracking_rule_id

    rules = list_tracking_rules(db_conn)
    assert len(rules) == 1


def test_filter_enabled_rules(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="A", rule_type="keyword", query="x", enabled=True)
    create_tracking_rule(db_conn, name="B", rule_type="keyword", query="y", enabled=False)
    enabled_rules = list_tracking_rules(db_conn, enabled=True)
    disabled_rules = list_tracking_rules(db_conn, enabled=False)
    assert len(enabled_rules) == 1
    assert enabled_rules[0].enabled is True
    assert len(disabled_rules) == 1
    assert disabled_rules[0].enabled is False


def test_update_name_query_schedule(db_conn: sqlite3.Connection) -> None:
    rule = create_tracking_rule(db_conn, name="A", rule_type="author", query="Alice")
    updated = update_tracking_rule(
        db_conn,
        rule.tracking_rule_id,
        name="Alice Follow",
        query="Alice Smith",
        schedule="weekly",
    )
    assert updated.name == "Alice Follow"
    assert updated.query == "Alice Smith"
    assert updated.schedule == "weekly"


def test_enable_disable_rule(db_conn: sqlite3.Connection) -> None:
    rule = create_tracking_rule(db_conn, name="A", rule_type="topic", query="ml")
    disabled = update_tracking_rule(db_conn, rule.tracking_rule_id, enabled=False)
    assert disabled.enabled is False
    enabled = update_tracking_rule(db_conn, rule.tracking_rule_id, enabled=True)
    assert enabled.enabled is True


def test_delete_rule(db_conn: sqlite3.Connection) -> None:
    rule = create_tracking_rule(db_conn, name="A", rule_type="keyword", query="ml")
    delete_tracking_rule(db_conn, rule.tracking_rule_id)
    assert get_tracking_rule(db_conn, rule.tracking_rule_id) is None


def test_delete_rule_preserves_historical_provenance(
    db_conn: sqlite3.Connection,
) -> None:
    rule = create_tracking_rule(db_conn, name="A", rule_type="keyword", query="ml")
    db_conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id, title)
        VALUES ('r1', 'tracking_rule', ?, 'arxiv', '2401.00001', 'Candidate')
        """,
        (rule.tracking_rule_id,),
    )
    db_conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, source_external_id)
        VALUES ('s1', 'v1|s1', 'r1', 'tracking_rule', ?, ?, 'arxiv', '2401.00001')
        """,
        (rule.tracking_rule_id, rule.tracking_rule_id),
    )

    delete_tracking_rule(db_conn, rule.tracking_rule_id)

    assert get_tracking_rule(db_conn, rule.tracking_rule_id) is None
    row = db_conn.execute(
        "SELECT tracking_rule_id, trigger_ref FROM discovery_result_sources WHERE source_id = 's1'"
    ).fetchone()
    assert tuple(row) == (None, rule.tracking_rule_id)


def test_delete_rule_with_cleanup_deletes_new_rule_only_candidate(
    db_conn: sqlite3.Connection,
) -> None:
    rule = create_tracking_rule(db_conn, name="A", rule_type="keyword", query="ml")
    db_conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id, title, status)
        VALUES ('r1', 'tracking_rule', ?, 'arxiv', '2401.00001', 'Candidate', 'new')
        """,
        (rule.tracking_rule_id,),
    )
    db_conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, source_external_id)
        VALUES ('s1', 'v1|s1', 'r1', 'tracking_rule', ?, ?, 'arxiv', '2401.00001')
        """,
        (rule.tracking_rule_id, rule.tracking_rule_id),
    )

    report = delete_tracking_rule(
        db_conn,
        rule.tracking_rule_id,
        delete_new_discovery=True,
    )

    assert report.deleted_discovery_count == 1
    assert get_tracking_rule(db_conn, rule.tracking_rule_id) is None
    result_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert result_count == 0
    assert source_count == 0


@pytest.mark.parametrize(
    ("status", "review_action", "imported_paper_id"),
    [
        ("saved", "save_for_later", None),
        ("reviewed", "link_to_existing", None),
        ("imported", "import", "p1"),
    ],
)
def test_delete_rule_with_cleanup_preserves_reviewed_or_imported_candidates(
    db_conn: sqlite3.Connection,
    status: str,
    review_action: str,
    imported_paper_id: str | None,
) -> None:
    rule = create_tracking_rule(db_conn, name="A", rule_type="keyword", query="ml")
    if imported_paper_id:
        db_conn.execute(
            "INSERT INTO papers (paper_id, title, workflow_status) VALUES (?, 'Paper', 'inbox')",
            (imported_paper_id,),
        )
    db_conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id,
         title, status, review_action, imported_paper_id)
        VALUES ('r1', 'tracking_rule', ?, 'arxiv', '2401.00001',
                'Candidate', ?, ?, ?)
        """,
        (rule.tracking_rule_id, status, review_action, imported_paper_id),
    )
    db_conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, source_external_id)
        VALUES ('s1', 'v1|s1', 'r1', 'tracking_rule', ?, ?, 'arxiv', '2401.00001')
        """,
        (rule.tracking_rule_id, rule.tracking_rule_id),
    )

    report = delete_tracking_rule(
        db_conn,
        rule.tracking_rule_id,
        delete_new_discovery=True,
    )

    assert report.deleted_discovery_count == 0
    result_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    row = db_conn.execute(
        "SELECT tracking_rule_id, trigger_ref FROM discovery_result_sources WHERE source_id = 's1'"
    ).fetchone()
    assert result_count == 1
    assert tuple(row) == (None, rule.tracking_rule_id)


def test_delete_rule_with_cleanup_preserves_multi_source_candidate(
    db_conn: sqlite3.Connection,
) -> None:
    rule = create_tracking_rule(db_conn, name="A", rule_type="keyword", query="ml")
    db_conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id, title, status)
        VALUES ('r1', 'tracking_rule', ?, 'arxiv', '2401.00001', 'Candidate', 'new')
        """,
        (rule.tracking_rule_id,),
    )
    db_conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, source_external_id)
        VALUES ('s1', 'v1|s1', 'r1', 'tracking_rule', ?, ?, 'arxiv', '2401.00001')
        """,
        (rule.tracking_rule_id, rule.tracking_rule_id),
    )
    db_conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, source, source_external_id)
        VALUES ('s2', 'v1|s2', 'r1', 'topic_anchor', 'graph', 'semantic_scholar', 'S2-1')
        """
    )

    report = delete_tracking_rule(
        db_conn,
        rule.tracking_rule_id,
        delete_new_discovery=True,
    )

    assert report.deleted_discovery_count == 0
    result_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_rows = db_conn.execute(
        "SELECT source_id, tracking_rule_id, trigger_ref FROM discovery_result_sources ORDER BY source_id"
    ).fetchall()
    assert result_count == 1
    assert [tuple(row) for row in source_rows] == [
        ("s1", None, rule.tracking_rule_id),
        ("s2", None, "graph"),
    ]


def test_update_missing_rule_raises(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not found"):
        update_tracking_rule(db_conn, "missing", name="x")


def test_delete_missing_rule_raises(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not found"):
        delete_tracking_rule(db_conn, "missing")


def test_invalid_rule_type_raises(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Unsupported tracking rule type"):
        create_tracking_rule(db_conn, name="A", rule_type="bad", query="x")


def test_create_citation_rule_validates_and_canonicalizes_query(
    db_conn: sqlite3.Connection,
) -> None:
    db_conn.execute(
        "INSERT INTO papers (paper_id, title, doi, workflow_status) "
        "VALUES ('p1', 'Paper', '10.1234/test', 'inbox')"
    )
    query = serialize_citation_tracking_query(
        db_conn,
        paper_id="p1",
        direction="cited_by",
        limit=500,
    )
    rule = create_tracking_rule(
        db_conn,
        name="Citations",
        rule_type="citation",
        query=query,
    )

    payload = json.loads(rule.query)
    assert payload == {
        "schema_version": 1,
        "paper_id": "p1",
        "direction": "cited_by",
        "source": "semantic_scholar",
        "limit": 100,
    }


def test_create_citation_rule_rejects_unknown_paper(db_conn: sqlite3.Connection) -> None:
    query = json.dumps({
        "schema_version": 1,
        "paper_id": "missing",
        "direction": "cited_by",
        "source": "semantic_scholar",
        "limit": 20,
    })
    with pytest.raises(ValueError, match="Paper not found"):
        create_tracking_rule(db_conn, name="Citations", rule_type="citation", query=query)


def test_create_citation_rule_rejects_invalid_payload(db_conn: sqlite3.Connection) -> None:
    db_conn.execute(
        "INSERT INTO papers (paper_id, title, doi, workflow_status) "
        "VALUES ('p1', 'Paper', '10.1234/test', 'inbox')"
    )
    query = json.dumps({
        "schema_version": 1,
        "paper_id": "p1",
        "direction": "bad",
        "source": "semantic_scholar",
        "limit": 20,
    })
    with pytest.raises(ValueError, match="direction"):
        create_tracking_rule(db_conn, name="Citations", rule_type="citation", query=query)


def test_create_openalex_author_rule_accepts_stable_id_and_canonicalizes(
    db_conn: sqlite3.Connection,
) -> None:
    query = serialize_openalex_author_tracking_query(
        author_id="A123456789",
        display_name=" Alice Smith ",
        limit=500,
    )
    rule = create_tracking_rule(
        db_conn,
        name="OpenAlex Alice",
        rule_type="openalex_author",
        query=query,
    )

    payload = json.loads(rule.query)
    assert payload == {
        "schema_version": 1,
        "author_id": "https://openalex.org/A123456789",
        "display_name": "Alice Smith",
        "source": "openalex",
        "limit": 100,
    }


@pytest.mark.parametrize(
    "query",
    [
        "Alice Smith",
        '{"schema_version":1,"author_id":"Alice Smith","source":"openalex","limit":20}',
        '{"schema_version":1,"author_id":["A1","A2"],"source":"openalex","limit":20}',
        '{"schema_version":1,"author_id":"A123","source":"openalex","institution_id":"I1","limit":20}',
        '{"schema_version":1,"author_id":"A123","source":"bad","limit":20}',
    ],
)
def test_create_openalex_author_rule_rejects_invalid_payloads(
    db_conn: sqlite3.Connection,
    query: str,
) -> None:
    with pytest.raises(ValueError):
        create_tracking_rule(
            db_conn,
            name="OpenAlex Bad",
            rule_type="openalex_author",
            query=query,
        )
