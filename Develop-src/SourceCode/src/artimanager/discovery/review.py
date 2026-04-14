"""Shared discovery inbox review actions for CLI and web routes."""

from __future__ import annotations

import json
from dataclasses import dataclass

from artimanager.config import AppConfig
from artimanager.db.utils import new_id, now_iso
from artimanager.tracking.manager import (
    create_tracking_rule,
    get_tracking_rule,
    update_tracking_rule,
)

DISCOVERY_REVIEW_ACTIONS = (
    "ignore",
    "save_for_later",
    "import",
    "link_to_existing",
    "follow_author",
    "mute_topic",
    "snooze",
)


@dataclass
class DiscoveryReviewOutcome:
    """Outcome of one discovery review action."""

    result_id: str
    action: str
    status: str
    message: str
    imported_paper_id: str | None = None
    tracking_rule_id: str | None = None
    followed_author: str | None = None


def _year_from_published(published_at: str | int | None) -> int | None:
    if published_at is None:
        return None
    if isinstance(published_at, int):
        return published_at
    text = str(published_at).strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _parse_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    return []


def review_discovery_result(
    conn,
    cfg: AppConfig,
    *,
    result_id: str,
    action: str,
    link_to_paper: str | None = None,
    author_name: str | None = None,
) -> DiscoveryReviewOutcome:
    """Apply one review action to a discovery result.

    This function performs writes but does not commit or rollback.
    Caller owns transaction boundaries.
    """
    if action not in DISCOVERY_REVIEW_ACTIONS:
        raise ValueError(f"Unsupported discovery review action: {action!r}")

    row = conn.execute(
        "SELECT discovery_result_id, source, external_id, title, authors, abstract, "
        "published_at, doi, arxiv_id, trigger_type, trigger_ref, "
        "status, review_action, imported_paper_id "
        "FROM discovery_results WHERE discovery_result_id = ?",
        (result_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Discovery result {result_id} not found.")

    if action == "ignore":
        conn.execute(
            "UPDATE discovery_results SET status = 'ignored', review_action = 'ignore' "
            "WHERE discovery_result_id = ?",
            (result_id,),
        )
        return DiscoveryReviewOutcome(
            result_id=result_id,
            action=action,
            status="ignored",
            message=f"Result {result_id} marked as ignored.",
        )

    if action == "save_for_later":
        conn.execute(
            "UPDATE discovery_results SET status = 'saved', review_action = 'save_for_later' "
            "WHERE discovery_result_id = ?",
            (result_id,),
        )
        return DiscoveryReviewOutcome(
            result_id=result_id,
            action=action,
            status="saved",
            message=f"Result {result_id} saved for later.",
        )

    if action == "import":
        existing_paper_id = row["imported_paper_id"]
        if row["status"] == "imported":
            if not existing_paper_id:
                raise ValueError(
                    f"Discovery result {result_id} is already imported but missing imported_paper_id"
                )
            return DiscoveryReviewOutcome(
                result_id=result_id,
                action=action,
                status="imported",
                message=f"Result {result_id} already imported as paper {existing_paper_id}.",
                imported_paper_id=existing_paper_id,
            )

        paper_id = new_id()
        now = now_iso()
        authors = _parse_authors(row["authors"])
        year = _year_from_published(row["published_at"])
        conn.execute(
            """INSERT INTO papers
               (paper_id, title, authors, year, abstract, doi, arxiv_id,
                workflow_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'inbox', ?, ?)""",
            (
                paper_id,
                row["title"],
                json.dumps(authors) if authors else None,
                year,
                row["abstract"],
                row["doi"],
                row["arxiv_id"],
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE discovery_results SET status = 'imported', "
            "review_action = 'import', imported_paper_id = ? "
            "WHERE discovery_result_id = ?",
            (paper_id, result_id),
        )
        return DiscoveryReviewOutcome(
            result_id=result_id,
            action=action,
            status="imported",
            message=f"Result {result_id} imported as paper {paper_id}.",
            imported_paper_id=paper_id,
        )

    if action == "link_to_existing":
        if not link_to_paper:
            raise ValueError("--link-to-paper is required for link_to_existing")
        existing = conn.execute(
            "SELECT paper_id FROM papers WHERE paper_id = ?",
            (link_to_paper,),
        ).fetchone()
        if existing is None:
            raise ValueError(f"Paper {link_to_paper} not found.")
        conn.execute(
            "UPDATE discovery_results SET status = 'reviewed', "
            "review_action = 'link_to_existing', imported_paper_id = ? "
            "WHERE discovery_result_id = ?",
            (link_to_paper, result_id),
        )
        return DiscoveryReviewOutcome(
            result_id=result_id,
            action=action,
            status="reviewed",
            message=f"Result {result_id} linked to paper {link_to_paper}.",
            imported_paper_id=link_to_paper,
        )

    if action == "follow_author":
        if row["review_action"] == "follow_author":
            return DiscoveryReviewOutcome(
                result_id=result_id,
                action=action,
                status=row["status"] or "reviewed",
                message=f"Result {result_id} already processed with follow_author.",
            )

        authors = _parse_authors(row["authors"])
        target_author = (author_name or "").strip() or (authors[0] if authors else "")
        if not target_author:
            raise ValueError(
                "follow_author requires --author-name or at least one author in the result"
            )
        rule = create_tracking_rule(
            conn,
            name=f"Follow {target_author}",
            rule_type="author",
            query=target_author,
            schedule=cfg.tracking_schedule,
            enabled=True,
        )
        conn.execute(
            "UPDATE discovery_results SET status = 'reviewed', review_action = 'follow_author' "
            "WHERE discovery_result_id = ?",
            (result_id,),
        )
        return DiscoveryReviewOutcome(
            result_id=result_id,
            action=action,
            status="reviewed",
            message=(
                f"Result {result_id} followed author '{target_author}' "
                f"via rule {rule.tracking_rule_id}."
            ),
            tracking_rule_id=rule.tracking_rule_id,
            followed_author=target_author,
        )

    if action == "mute_topic":
        trigger_type = row["trigger_type"]
        trigger_ref = row["trigger_ref"]
        if trigger_type != "tracking_rule" or not trigger_ref:
            raise ValueError("mute_topic is only valid for tracking_rule results")
        rule = get_tracking_rule(conn, trigger_ref)
        if rule is None:
            raise ValueError(f"Tracking rule not found: {trigger_ref}")
        if rule.rule_type not in {"keyword", "topic", "category"}:
            raise ValueError("mute_topic only applies to keyword/topic/category rules")
        update_tracking_rule(conn, trigger_ref, enabled=False)
        conn.execute(
            "UPDATE discovery_results SET status = 'reviewed', review_action = 'mute_topic' "
            "WHERE discovery_result_id = ?",
            (result_id,),
        )
        return DiscoveryReviewOutcome(
            result_id=result_id,
            action=action,
            status="reviewed",
            message=f"Result {result_id} muted by disabling tracking rule {trigger_ref}.",
            tracking_rule_id=trigger_ref,
        )

    # action == "snooze"
    conn.execute(
        "UPDATE discovery_results SET status = 'saved', review_action = 'snooze' "
        "WHERE discovery_result_id = ?",
        (result_id,),
    )
    return DiscoveryReviewOutcome(
        result_id=result_id,
        action=action,
        status="saved",
        message=f"Result {result_id} snoozed.",
    )
