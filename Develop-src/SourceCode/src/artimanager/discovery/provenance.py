"""Discovery result provenance storage helpers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, replace
from typing import Any

from artimanager.db.utils import new_id


@dataclass(frozen=True)
class DiscoverySourceContext:
    """Context explaining why a discovery candidate was stored."""

    trigger_type: str
    source: str
    trigger_ref: str | None = None
    tracking_rule_id: str | None = None
    direction: str | None = None
    anchor_paper_id: str | None = None
    anchor_external_id: str | None = None
    anchor_author_id: str | None = None
    anchor_institution_id: str | None = None
    source_external_id: str | None = None
    relevance_score: float | None = None
    relevance_context: str | None = None


@dataclass(frozen=True)
class StoreDiscoveryOutcome:
    """Result of candidate + provenance storage."""

    discovery_result_id: str
    candidate_inserted: bool
    provenance_inserted: bool


def _key_part(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace("|", "\\|")


def build_provenance_key(context: DiscoverySourceContext) -> str:
    """Build a deterministic idempotency key for one provenance source."""
    candidate = f"{context.source}:{context.source_external_id or ''}"
    parts = [
        ("trigger_type", context.trigger_type),
        ("trigger_ref", context.trigger_ref),
        ("rule", context.tracking_rule_id),
        ("source", context.source),
        ("direction", context.direction),
        ("anchor_paper", context.anchor_paper_id),
        ("anchor_external", context.anchor_external_id),
        ("anchor_author", context.anchor_author_id),
        ("anchor_institution", context.anchor_institution_id),
        ("candidate", candidate),
    ]
    return "v1|" + "|".join(f"{name}={_key_part(value)}" for name, value in parts)


def find_existing_discovery_result_id(
    conn: sqlite3.Connection,
    *,
    source: str,
    external_id: str | None,
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> str | None:
    """Find an existing candidate by DOI, arXiv ID, then source/external ID."""
    if doi:
        row = conn.execute(
            "SELECT discovery_result_id FROM discovery_results WHERE doi = ?",
            (doi,),
        ).fetchone()
        if row is not None:
            return row[0]

    if arxiv_id:
        row = conn.execute(
            "SELECT discovery_result_id FROM discovery_results WHERE arxiv_id = ?",
            (arxiv_id,),
        ).fetchone()
        if row is not None:
            return row[0]

    if not external_id:
        return None
    row = conn.execute(
        "SELECT discovery_result_id FROM discovery_results WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def _insert_discovery_result(conn: sqlite3.Connection, record: Any) -> str:
    conn.execute(
        """INSERT INTO discovery_results
           (discovery_result_id, trigger_type, trigger_ref, source, external_id,
            title, authors, abstract, doi, arxiv_id, published_at, relevance_score,
            relevance_context, status, review_action, imported_paper_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record.discovery_result_id,
            record.trigger_type,
            record.trigger_ref,
            record.source,
            record.external_id,
            record.title,
            json.dumps(record.authors) if record.authors else None,
            record.abstract or None,
            record.doi,
            record.arxiv_id,
            record.published_at,
            record.relevance_score,
            record.relevance_context,
            record.status,
            record.review_action,
            record.imported_paper_id,
        ),
    )
    return record.discovery_result_id


def _context_with_record_defaults(
    record: Any,
    context: DiscoverySourceContext,
) -> DiscoverySourceContext:
    return replace(
        context,
        source=context.source or record.source,
        source_external_id=context.source_external_id or record.external_id,
        relevance_score=(
            context.relevance_score
            if context.relevance_score is not None
            else record.relevance_score
        ),
        relevance_context=(
            context.relevance_context
            if context.relevance_context is not None
            else record.relevance_context
        ),
    )


def store_discovery_record_with_source(
    conn: sqlite3.Connection,
    record: Any,
    source_context: DiscoverySourceContext,
) -> StoreDiscoveryOutcome:
    """Store one candidate and its provenance source as one atomic operation."""
    if not record.external_id and not record.doi and not record.arxiv_id:
        return StoreDiscoveryOutcome(record.discovery_result_id, False, False)

    context = _context_with_record_defaults(record, source_context)
    provenance_key = build_provenance_key(context)
    savepoint = f"discovery_store_{uuid.uuid4().hex}"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        existing_source = conn.execute(
            """
            SELECT discovery_result_id FROM discovery_result_sources
            WHERE provenance_key = ?
            """,
            (provenance_key,),
        ).fetchone()
        if existing_source is not None:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            return StoreDiscoveryOutcome(existing_source[0], False, False)

        existing_id = find_existing_discovery_result_id(
            conn,
            source=record.source,
            external_id=record.external_id,
            doi=record.doi,
            arxiv_id=record.arxiv_id,
        )
        candidate_inserted = existing_id is None
        discovery_result_id = existing_id or _insert_discovery_result(conn, record)

        conn.execute(
            """INSERT INTO discovery_result_sources
               (source_id, provenance_key, discovery_result_id, trigger_type,
                trigger_ref, tracking_rule_id, source, direction, anchor_paper_id,
                anchor_external_id, anchor_author_id, anchor_institution_id,
                source_external_id, relevance_score, relevance_context)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id(),
                provenance_key,
                discovery_result_id,
                context.trigger_type,
                context.trigger_ref,
                context.tracking_rule_id,
                context.source,
                context.direction,
                context.anchor_paper_id,
                context.anchor_external_id,
                context.anchor_author_id,
                context.anchor_institution_id,
                context.source_external_id,
                context.relevance_score,
                context.relevance_context,
            ),
        )
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return StoreDiscoveryOutcome(discovery_result_id, candidate_inserted, True)
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def list_discovery_sources(
    conn: sqlite3.Connection,
    discovery_result_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Return provenance rows grouped by discovery_result_id."""
    if not discovery_result_ids:
        return {}
    table_row = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'discovery_result_sources'
        """
    ).fetchone()
    if table_row is None:
        return {rid: [] for rid in discovery_result_ids}
    placeholders = ", ".join("?" for _ in discovery_result_ids)
    rows = conn.execute(
        f"""
        SELECT discovery_result_id, source_id, trigger_type, trigger_ref,
               tracking_rule_id, source, direction, anchor_paper_id,
               anchor_external_id, anchor_author_id, anchor_institution_id,
               source_external_id, relevance_score, relevance_context, created_at
        FROM discovery_result_sources
        WHERE discovery_result_id IN ({placeholders})
        ORDER BY created_at ASC, source_id ASC
        """,
        discovery_result_ids,
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {rid: [] for rid in discovery_result_ids}
    for row in rows:
        grouped.setdefault(row[0], []).append(
            {
                "source_id": row[1],
                "trigger_type": row[2],
                "trigger_ref": row[3],
                "tracking_rule_id": row[4],
                "source": row[5],
                "direction": row[6],
                "anchor_paper_id": row[7],
                "anchor_external_id": row[8],
                "anchor_author_id": row[9],
                "anchor_institution_id": row[10],
                "source_external_id": row[11],
                "relevance_score": row[12],
                "relevance_context": row[13],
                "created_at": row[14],
            }
        )
    return grouped
