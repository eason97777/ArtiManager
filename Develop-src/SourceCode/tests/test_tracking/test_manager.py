"""Tests for tracking.manager."""

from __future__ import annotations

import sqlite3

import pytest

from artimanager.tracking.manager import (
    create_tracking_rule,
    delete_tracking_rule,
    get_tracking_rule,
    list_tracking_rules,
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


def test_update_missing_rule_raises(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not found"):
        update_tracking_rule(db_conn, "missing", name="x")


def test_delete_missing_rule_raises(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not found"):
        delete_tracking_rule(db_conn, "missing")


def test_invalid_rule_type_raises(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Unsupported tracking rule type"):
        create_tracking_rule(db_conn, name="A", rule_type="bad", query="x")
