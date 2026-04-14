"""Tracking rule CRUD for Phase 9."""

from __future__ import annotations

from dataclasses import dataclass

from artimanager.db.utils import new_id, now_iso

_VALID_RULE_TYPES = {"keyword", "topic", "author", "category"}


@dataclass
class TrackingRule:
    """A persisted arXiv tracking rule."""

    tracking_rule_id: str
    name: str
    rule_type: str
    query: str
    schedule: str | None
    enabled: bool
    created_at: str


def _to_rule(row) -> TrackingRule:
    return TrackingRule(
        tracking_rule_id=row[0],
        name=row[1],
        rule_type=row[2],
        query=row[3],
        schedule=row[4],
        enabled=bool(row[5]),
        created_at=row[6],
    )


def create_tracking_rule(
    conn,
    *,
    name: str,
    rule_type: str,
    query: str,
    schedule: str | None = None,
    enabled: bool = True,
) -> TrackingRule:
    if rule_type not in _VALID_RULE_TYPES:
        raise ValueError(f"Unsupported tracking rule type: {rule_type!r}")
    if not query.strip():
        raise ValueError("Tracking rule query must not be empty")

    tracking_rule_id = new_id()
    created_at = now_iso()
    conn.execute(
        """INSERT INTO tracking_rules
           (tracking_rule_id, name, rule_type, query, schedule, enabled, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (tracking_rule_id, name, rule_type, query, schedule, 1 if enabled else 0, created_at),
    )
    return TrackingRule(
        tracking_rule_id=tracking_rule_id,
        name=name,
        rule_type=rule_type,
        query=query,
        schedule=schedule,
        enabled=enabled,
        created_at=created_at,
    )


def get_tracking_rule(conn, tracking_rule_id: str) -> TrackingRule | None:
    row = conn.execute(
        "SELECT tracking_rule_id, name, rule_type, query, schedule, enabled, created_at "
        "FROM tracking_rules WHERE tracking_rule_id = ?",
        (tracking_rule_id,),
    ).fetchone()
    if row is None:
        return None
    return _to_rule(row)


def list_tracking_rules(conn, *, enabled: bool | None = None) -> list[TrackingRule]:
    sql = (
        "SELECT tracking_rule_id, name, rule_type, query, schedule, enabled, created_at "
        "FROM tracking_rules"
    )
    params: list = []
    if enabled is not None:
        sql += " WHERE enabled = ?"
        params.append(1 if enabled else 0)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return [_to_rule(r) for r in rows]


def update_tracking_rule(
    conn,
    tracking_rule_id: str,
    *,
    name: str | None = None,
    query: str | None = None,
    schedule: str | None = None,
    enabled: bool | None = None,
) -> TrackingRule:
    current = get_tracking_rule(conn, tracking_rule_id)
    if current is None:
        raise ValueError(f"Tracking rule not found: {tracking_rule_id}")

    new_name = name if name is not None else current.name
    new_query = query if query is not None else current.query
    new_schedule = schedule if schedule is not None else current.schedule
    new_enabled = enabled if enabled is not None else current.enabled

    if not new_query.strip():
        raise ValueError("Tracking rule query must not be empty")

    conn.execute(
        "UPDATE tracking_rules SET name = ?, query = ?, schedule = ?, enabled = ? "
        "WHERE tracking_rule_id = ?",
        (new_name, new_query, new_schedule, 1 if new_enabled else 0, tracking_rule_id),
    )
    return TrackingRule(
        tracking_rule_id=tracking_rule_id,
        name=new_name,
        rule_type=current.rule_type,
        query=new_query,
        schedule=new_schedule,
        enabled=new_enabled,
        created_at=current.created_at,
    )


def delete_tracking_rule(conn, tracking_rule_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM tracking_rules WHERE tracking_rule_id = ?",
        (tracking_rule_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Tracking rule not found: {tracking_rule_id}")
    conn.execute(
        "DELETE FROM tracking_rules WHERE tracking_rule_id = ?",
        (tracking_rule_id,),
    )
