"""Small read models for Web templates."""

from __future__ import annotations

from typing import Any

from artimanager.discovery.provenance import list_discovery_sources
from artimanager.tracking.manager import (
    parse_citation_tracking_query,
    parse_openalex_author_tracking_query,
)

_UNUSABLE_SUMMARY_PATTERNS = (
    "i don't see any text provided",
    "could you paste the full text",
    "please provide the text",
    "provide the text you'd like me to summarize",
)


def compact_author_list(authors: list[str], *, max_visible: int = 3) -> str:
    """Return a compact one-line author display string."""
    clean_authors = [author.strip() for author in authors if author and author.strip()]
    if not clean_authors:
        return "(unknown)"
    if len(clean_authors) <= max_visible:
        return ", ".join(clean_authors)
    visible = ", ".join(clean_authors[:max_visible])
    omitted = len(clean_authors) - max_visible
    return f"{visible}, +{omitted} more"


def tracking_rule_summary(rule_type: str, query: str) -> dict[str, Any]:
    """Return a readable tracking rule summary while preserving raw query."""
    if rule_type in {"keyword", "topic", "author", "category"}:
        return {
            "summary": query,
            "details": [],
            "invalid": False,
        }
    if rule_type == "citation":
        try:
            payload = parse_citation_tracking_query(query)
        except ValueError as exc:
            return {
                "summary": f"Invalid payload: {exc}",
                "details": [],
                "invalid": True,
            }
        return {
            "summary": f"Citation {payload.direction} for paper {payload.paper_id}",
            "details": [
                f"source: {payload.source}",
                f"limit: {payload.limit}",
            ],
            "invalid": False,
        }
    if rule_type == "openalex_author":
        try:
            payload = parse_openalex_author_tracking_query(query)
        except ValueError as exc:
            return {
                "summary": f"Invalid payload: {exc}",
                "details": [],
                "invalid": True,
            }
        author_label = payload.author_id
        if payload.display_name:
            author_label = f"{payload.display_name} / {payload.author_id}"
        return {
            "summary": f"OpenAlex author watch: {author_label}",
            "details": [
                f"source: {payload.source}",
                f"limit: {payload.limit}",
            ],
            "invalid": False,
        }
    return {
        "summary": query,
        "details": [],
        "invalid": False,
    }


def clean_relevance_context_for_display(
    context: str | None,
    *,
    relevance_score: float | None = None,
) -> str | None:
    """Sanitize legacy bad summary text for display without mutating storage."""
    if not context:
        return None
    lines = []
    changed = False
    suppress_local_matches = relevance_score is None or relevance_score <= 0
    skipping_old_local_matches = False
    for line in context.splitlines():
        if line.lower().startswith("summary:"):
            lowered = line.lower()
            if any(pattern in lowered for pattern in _UNUSABLE_SUMMARY_PATTERNS):
                lines.append("Summary: Summary unavailable: provider did not return a usable summary")
                changed = True
                continue
        if line.strip() == "Local matches:":
            lines.append("Local title-overlap matches:")
            changed = True
            skipping_old_local_matches = suppress_local_matches
            if suppress_local_matches:
                lines.append("- (none)")
            continue
        if skipping_old_local_matches:
            if line.startswith("- "):
                changed = True
                continue
            skipping_old_local_matches = False
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        return None
    return cleaned if changed else context


def _load_tracking_rule_map(conn, tracking_rule_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not tracking_rule_ids:
        return {}
    placeholders = ", ".join("?" for _ in tracking_rule_ids)
    rows = conn.execute(
        f"""
        SELECT tracking_rule_id, name, rule_type, query
        FROM tracking_rules
        WHERE tracking_rule_id IN ({placeholders})
        """,
        list(tracking_rule_ids),
    ).fetchall()
    return {
        row[0]: {
            "tracking_rule_id": row[0],
            "name": row[1],
            "rule_type": row[2],
            "query": row[3],
            "query_summary": tracking_rule_summary(row[2], row[3]),
        }
        for row in rows
    }


def _provenance_summary(item: dict[str, Any], rule: dict[str, Any] | None) -> str:
    source = item.get("source") or "unknown"
    trigger_type = item.get("trigger_type") or "unknown"
    direction = item.get("direction")

    if trigger_type == "topic_anchor":
        return f"Topic discovery via {source}"
    if trigger_type == "paper_anchor":
        paper_id = item.get("anchor_paper_id") or item.get("trigger_ref") or "(unknown paper)"
        return f"Paper-anchored discovery from paper {paper_id}"
    if trigger_type == "tracking_rule":
        if direction in {"cited_by", "references"}:
            paper_id = item.get("anchor_paper_id") or "(unknown paper)"
            anchor = item.get("anchor_external_id") or "(unknown anchor)"
            return f"Citation tracking: {direction} for paper {paper_id} using {anchor}"
        if direction == "openalex_author_work":
            rule_summary = (rule or {}).get("query_summary") or {}
            summary = rule_summary.get("summary")
            if summary and not rule_summary.get("invalid"):
                return summary
            author_id = item.get("anchor_author_id") or "(unknown author)"
            return f"OpenAlex author watch: {author_id}"
        if rule:
            return f"Tracking rule {rule['name']} found this candidate"
        rule_id = item.get("tracking_rule_id") or item.get("trigger_ref") or "(missing rule)"
        return f"Tracking rule {rule_id} found this candidate"
    return f"{trigger_type} via {source}"


def format_provenance_item(
    item: dict[str, Any],
    *,
    rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact template-friendly provenance dictionary."""
    details: list[str] = []
    if rule:
        details.append(f"rule: {rule['name']} ({rule['rule_type']})")
    elif item.get("tracking_rule_id"):
        details.append(f"rule id: {item['tracking_rule_id']}")
    elif item.get("trigger_type") == "tracking_rule" and item.get("trigger_ref"):
        details.append(f"rule id: {item['trigger_ref']}")
    elif item.get("trigger_ref"):
        details.append(f"trigger ref: {item['trigger_ref']}")
    for key, label in [
        ("source", "source"),
        ("trigger_type", "trigger"),
        ("direction", "direction"),
        ("anchor_paper_id", "anchor paper"),
        ("anchor_external_id", "anchor external"),
        ("anchor_author_id", "anchor author"),
        ("source_external_id", "source external"),
        ("relevance_score", "score"),
        ("created_at", "created"),
    ]:
        value = item.get(key)
        if value not in {None, ""}:
            details.append(f"{label}: {value}")
    cleaned_context = clean_relevance_context_for_display(
        item.get("relevance_context"),
        relevance_score=item.get("relevance_score"),
    )
    if cleaned_context:
        details.append(f"context: {cleaned_context}")

    return {
        "summary": _provenance_summary(item, rule),
        "details": details,
        "source": item.get("source"),
        "direction": item.get("direction"),
        "tracking_rule": rule,
    }


def load_provenance_views(
    conn,
    discovery_result_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Load grouped, formatted provenance for discovery results."""
    grouped = list_discovery_sources(conn, discovery_result_ids)
    tracking_rule_ids = {
        item["tracking_rule_id"]
        for items in grouped.values()
        for item in items
        if item.get("tracking_rule_id")
    }
    rules = _load_tracking_rule_map(conn, tracking_rule_ids)
    return {
        result_id: [
            format_provenance_item(
                item,
                rule=rules.get(item.get("tracking_rule_id")),
            )
            for item in items
        ]
        for result_id, items in grouped.items()
    }


def tracking_rule_view(rule) -> dict[str, Any]:
    """Return a template-friendly tracking rule dictionary."""
    return {
        "tracking_rule_id": rule.tracking_rule_id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "query": rule.query,
        "query_summary": tracking_rule_summary(rule.rule_type, rule.query),
        "schedule": rule.schedule,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
    }
