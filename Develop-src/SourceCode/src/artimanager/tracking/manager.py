"""Tracking rule CRUD for Phase 9."""

from __future__ import annotations

import json
from dataclasses import dataclass

from artimanager.db.utils import new_id, now_iso

_VALID_RULE_TYPES = {"keyword", "topic", "author", "category", "citation", "openalex_author"}
_CITATION_DIRECTIONS = {"cited_by", "references"}
_CITATION_SOURCE = "semantic_scholar"
_CITATION_LIMIT_MIN = 1
_CITATION_LIMIT_MAX = 100
_OPENALEX_SOURCE = "openalex"
_OPENALEX_LIMIT_MIN = 1
_OPENALEX_LIMIT_MAX = 100
_OPENALEX_UNSUPPORTED_KEYS = {"author_ids", "seed_paper", "institution_id", "coauthor_depth", "mode"}


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


@dataclass(frozen=True)
class CitationTrackingPayload:
    """Validated citation tracking rule payload."""

    schema_version: int
    paper_id: str
    direction: str
    source: str
    limit: int


@dataclass(frozen=True)
class OpenAlexAuthorTrackingPayload:
    """Validated OpenAlex author identity tracking payload."""

    schema_version: int
    author_id: str
    display_name: str | None
    source: str
    limit: int


@dataclass(frozen=True)
class TrackingRuleDeleteReport:
    """Summary of tracking rule deletion side effects."""

    tracking_rule_id: str
    deleted_discovery_count: int = 0
    preserved_discovery_count: int = 0


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


def _clamp_citation_limit(limit: int) -> int:
    return max(_CITATION_LIMIT_MIN, min(_CITATION_LIMIT_MAX, int(limit)))


def _clamp_openalex_limit(limit: int) -> int:
    return max(_OPENALEX_LIMIT_MIN, min(_OPENALEX_LIMIT_MAX, int(limit)))


def _ensure_citation_anchor_paper(conn, paper_id: str) -> None:
    row = conn.execute(
        "SELECT doi, arxiv_id FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Paper not found for citation tracking: {paper_id}")
    if not row[0] and not row[1]:
        raise ValueError(
            f"Paper {paper_id} has neither DOI nor arXiv ID for citation tracking"
        )


def parse_citation_tracking_query(query: str) -> CitationTrackingPayload:
    try:
        raw = json.loads(query)
    except json.JSONDecodeError as exc:
        raise ValueError("Citation tracking query must be a JSON object") from exc
    if not isinstance(raw, dict):
        raise ValueError("Citation tracking query must be a JSON object")

    schema_version = raw.get("schema_version")
    if schema_version != 1:
        raise ValueError("Citation tracking schema_version must be 1")

    paper_id = str(raw.get("paper_id") or "").strip()
    if not paper_id:
        raise ValueError("Citation tracking paper_id is required")

    direction = str(raw.get("direction") or "").strip()
    if direction not in _CITATION_DIRECTIONS:
        raise ValueError("Citation tracking direction must be 'cited_by' or 'references'")

    source = str(raw.get("source") or "").strip()
    if source != _CITATION_SOURCE:
        raise ValueError("Citation tracking source must be 'semantic_scholar'")

    try:
        limit = _clamp_citation_limit(int(raw.get("limit", 20)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Citation tracking limit must be an integer") from exc

    return CitationTrackingPayload(
        schema_version=1,
        paper_id=paper_id,
        direction=direction,
        source=source,
        limit=limit,
    )


def serialize_citation_tracking_query(
    conn,
    *,
    paper_id: str,
    direction: str,
    limit: int = 20,
    source: str = _CITATION_SOURCE,
) -> str:
    paper_id = paper_id.strip()
    if not paper_id:
        raise ValueError("Citation tracking paper_id is required")
    if direction not in _CITATION_DIRECTIONS:
        raise ValueError("Citation tracking direction must be 'cited_by' or 'references'")
    if source != _CITATION_SOURCE:
        raise ValueError("Citation tracking source must be 'semantic_scholar'")
    _ensure_citation_anchor_paper(conn, paper_id)
    payload = {
        "schema_version": 1,
        "paper_id": paper_id,
        "direction": direction,
        "source": source,
        "limit": _clamp_citation_limit(limit),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _citation_payload_to_query(payload: CitationTrackingPayload) -> str:
    return json.dumps(
        {
            "schema_version": payload.schema_version,
            "paper_id": payload.paper_id,
            "direction": payload.direction,
            "source": payload.source,
            "limit": payload.limit,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_citation_tracking_query(conn, query: str) -> CitationTrackingPayload:
    payload = parse_citation_tracking_query(query)
    _ensure_citation_anchor_paper(conn, payload.paper_id)
    canonical = serialize_citation_tracking_query(
        conn,
        paper_id=payload.paper_id,
        direction=payload.direction,
        limit=payload.limit,
        source=payload.source,
    )
    return parse_citation_tracking_query(canonical)


def parse_openalex_author_tracking_query(query: str) -> OpenAlexAuthorTrackingPayload:
    try:
        raw = json.loads(query)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAlex author tracking query must be a JSON object") from exc
    if not isinstance(raw, dict):
        raise ValueError("OpenAlex author tracking query must be a JSON object")
    unsupported = sorted(key for key in _OPENALEX_UNSUPPORTED_KEYS if key in raw)
    if unsupported:
        raise ValueError(f"Unsupported OpenAlex author tracking field(s): {', '.join(unsupported)}")

    if raw.get("schema_version") != 1:
        raise ValueError("OpenAlex author tracking schema_version must be 1")
    author_id_raw = raw.get("author_id")
    if isinstance(author_id_raw, list):
        raise ValueError("OpenAlex author tracking accepts exactly one author_id")
    if not isinstance(author_id_raw, str):
        raise ValueError("OpenAlex author tracking author_id is required")
    from artimanager.discovery.openalex_api import normalize_openalex_author_id

    author_id = normalize_openalex_author_id(author_id_raw)

    source = str(raw.get("source") or "").strip()
    if source != _OPENALEX_SOURCE:
        raise ValueError("OpenAlex author tracking source must be 'openalex'")

    display_name_raw = raw.get("display_name")
    display_name = None
    if display_name_raw is not None:
        display_name = str(display_name_raw).strip() or None

    try:
        limit = _clamp_openalex_limit(int(raw.get("limit", 20)))
    except (TypeError, ValueError) as exc:
        raise ValueError("OpenAlex author tracking limit must be an integer") from exc

    return OpenAlexAuthorTrackingPayload(
        schema_version=1,
        author_id=author_id,
        display_name=display_name,
        source=_OPENALEX_SOURCE,
        limit=limit,
    )


def _openalex_payload_to_query(payload: OpenAlexAuthorTrackingPayload) -> str:
    data: dict[str, object] = {
        "schema_version": payload.schema_version,
        "author_id": payload.author_id,
        "source": payload.source,
        "limit": payload.limit,
    }
    if payload.display_name:
        data["display_name"] = payload.display_name
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def serialize_openalex_author_tracking_query(
    *,
    author_id: str,
    display_name: str | None = None,
    limit: int = 20,
    source: str = _OPENALEX_SOURCE,
) -> str:
    payload = {
        "schema_version": 1,
        "author_id": author_id,
        "source": source,
        "limit": _clamp_openalex_limit(limit),
    }
    if display_name is not None:
        payload["display_name"] = display_name.strip()
    return _openalex_payload_to_query(
        parse_openalex_author_tracking_query(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
    )


def validate_openalex_author_tracking_query(query: str) -> OpenAlexAuthorTrackingPayload:
    payload = parse_openalex_author_tracking_query(query)
    return parse_openalex_author_tracking_query(_openalex_payload_to_query(payload))


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
    if rule_type == "citation":
        query = _citation_payload_to_query(validate_citation_tracking_query(conn, query))
    if rule_type == "openalex_author":
        query = _openalex_payload_to_query(validate_openalex_author_tracking_query(query))

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
    if current.rule_type == "citation":
        new_query = _citation_payload_to_query(validate_citation_tracking_query(conn, new_query))
    if current.rule_type == "openalex_author":
        new_query = _openalex_payload_to_query(validate_openalex_author_tracking_query(new_query))

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


def _eligible_cleanup_result_ids(conn, tracking_rule_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT dr.discovery_result_id
        FROM discovery_results dr
        WHERE dr.status = 'new'
          AND dr.imported_paper_id IS NULL
          AND dr.review_action IS NULL
          AND EXISTS (
              SELECT 1
              FROM discovery_result_sources ds
              WHERE ds.discovery_result_id = dr.discovery_result_id
                AND ds.tracking_rule_id = ?
          )
          AND NOT EXISTS (
              SELECT 1
              FROM discovery_result_sources ds_other
              WHERE ds_other.discovery_result_id = dr.discovery_result_id
                AND NOT (
                    ds_other.trigger_type = 'tracking_rule'
                    AND (
                        ds_other.tracking_rule_id = ?
                        OR (
                            ds_other.tracking_rule_id IS NULL
                            AND ds_other.trigger_ref = ?
                        )
                    )
                )
          )
        """,
        (tracking_rule_id, tracking_rule_id, tracking_rule_id),
    ).fetchall()
    return [row[0] for row in rows]


def delete_tracking_rule(
    conn,
    tracking_rule_id: str,
    *,
    delete_new_discovery: bool = False,
) -> TrackingRuleDeleteReport:
    row = conn.execute(
        "SELECT 1 FROM tracking_rules WHERE tracking_rule_id = ?",
        (tracking_rule_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Tracking rule not found: {tracking_rule_id}")

    deleted_discovery_count = 0
    if delete_new_discovery:
        cleanup_ids = _eligible_cleanup_result_ids(conn, tracking_rule_id)
        deleted_discovery_count = len(cleanup_ids)
        if cleanup_ids:
            placeholders = ", ".join("?" for _ in cleanup_ids)
            conn.execute(
                f"""
                DELETE FROM discovery_result_sources
                WHERE discovery_result_id IN ({placeholders})
                """,
                cleanup_ids,
            )
            conn.execute(
                f"""
                DELETE FROM discovery_results
                WHERE discovery_result_id IN ({placeholders})
                """,
                cleanup_ids,
            )

    preserved_discovery_count = conn.execute(
        """
        SELECT COUNT(DISTINCT discovery_result_id)
        FROM discovery_result_sources
        WHERE tracking_rule_id = ?
        """,
        (tracking_rule_id,),
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE discovery_result_sources
        SET tracking_rule_id = NULL,
            trigger_ref = COALESCE(trigger_ref, ?)
        WHERE tracking_rule_id = ?
        """,
        (tracking_rule_id, tracking_rule_id),
    )
    conn.execute(
        "DELETE FROM tracking_rules WHERE tracking_rule_id = ?",
        (tracking_rule_id,),
    )
    return TrackingRuleDeleteReport(
        tracking_rule_id=tracking_rule_id,
        deleted_discovery_count=deleted_discovery_count,
        preserved_discovery_count=preserved_discovery_count,
    )
