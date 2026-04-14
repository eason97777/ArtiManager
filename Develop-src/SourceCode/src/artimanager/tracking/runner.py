"""Tracking runner for Phase 9 (CLI-invoked scheduled fetch)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from artimanager.agent.factory import create_provider
from artimanager.config import AppConfig
from artimanager.db.utils import new_id
from artimanager.discovery._models import ExternalPaper
from artimanager.discovery.arxiv_api import search as arxiv_search
from artimanager.discovery.engine import DiscoveryRecord, store_discovery_record
from artimanager.search.query import search_all
from artimanager.tracking.manager import get_tracking_rule, list_tracking_rules

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class TrackingRunReport:
    """Summary of one tracking run."""

    rules_processed: int = 0
    new_count: int = 0
    duplicate_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    records: list[DiscoveryRecord] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.new_count + self.duplicate_count + self.error_count


def _rule_to_arxiv_query(rule_type: str, query: str) -> str:
    if rule_type in {"keyword", "topic"}:
        return f"all:{query}"
    if rule_type == "author":
        escaped = query.replace('"', "")
        return f'au:"{escaped}"'
    if rule_type == "category":
        return f"cat:{query}"
    raise ValueError(f"Unsupported tracking rule type: {rule_type!r}")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _compute_relevance(conn, rule_query: str, candidate_title: str) -> tuple[float, list[tuple[str, str]]]:
    local_matches = search_all(conn, rule_query, limit=5)
    top3 = local_matches[:3]
    local_tokens: set[str] = set()
    local_titles: list[tuple[str, str]] = []
    for item in top3:
        local_tokens.update(_tokenize(item.title))
        local_titles.append((item.paper_id, item.title))

    candidate_tokens = _tokenize(candidate_title)
    if not candidate_tokens or not local_tokens:
        return 0.0, local_titles
    score = len(candidate_tokens & local_tokens) / len(candidate_tokens)
    return float(score), local_titles


def _build_relevance_context(
    *,
    summary: str,
    rule_name: str,
    rule_type: str,
    rule_query: str,
    local_titles: list[tuple[str, str]],
) -> str:
    lines = [
        f"Summary: {summary}",
        f"Tracking rule: {rule_name} ({rule_type}:{rule_query})",
        "Local matches:",
    ]
    if local_titles:
        for paper_id, title in local_titles:
            lines.append(f"- {paper_id}: {title or '(untitled)'}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def _to_discovery_record(
    paper: ExternalPaper,
    *,
    tracking_rule_id: str,
    relevance_score: float,
    relevance_context: str,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        discovery_result_id=new_id(),
        trigger_type="tracking_rule",
        trigger_ref=tracking_rule_id,
        source="arxiv",
        external_id=paper.external_id,
        title=paper.title,
        authors=paper.authors,
        abstract=paper.abstract,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        published_at=str(paper.year) if paper.year is not None else None,
        relevance_score=relevance_score,
        relevance_context=relevance_context,
        status="new",
        review_action=None,
        imported_paper_id=None,
    )


def _process_candidate(
    conn,
    provider,
    *,
    rule,
    paper: ExternalPaper,
    report: TrackingRunReport,
) -> None:
    if not paper.external_id:
        report.error_count += 1
        return

    summary = "Summary unavailable"
    if paper.abstract:
        try:
            summary = provider.summarize(paper.abstract)
        except (RuntimeError, NotImplementedError, ValueError) as exc:
            summary = f"Summary generation failed: {exc}"
            report.warning_count += 1

    relevance_score, local_titles = _compute_relevance(conn, rule.query, paper.title)
    relevance_context = _build_relevance_context(
        summary=summary,
        rule_name=rule.name,
        rule_type=rule.rule_type,
        rule_query=rule.query,
        local_titles=local_titles,
    )
    record = _to_discovery_record(
        paper,
        tracking_rule_id=rule.tracking_rule_id,
        relevance_score=relevance_score,
        relevance_context=relevance_context,
    )
    inserted = store_discovery_record(conn, record)
    if inserted:
        report.new_count += 1
        report.records.append(record)
    else:
        report.duplicate_count += 1


def run_tracking(
    conn,
    cfg: AppConfig,
    *,
    tracking_rule_id: str | None = None,
    limit: int = 20,
) -> TrackingRunReport:
    """Execute tracking rules and store results in discovery inbox."""
    report = TrackingRunReport()

    if tracking_rule_id:
        rule = get_tracking_rule(conn, tracking_rule_id)
        if rule is None:
            raise ValueError(f"Tracking rule not found: {tracking_rule_id}")
        if not rule.enabled:
            raise ValueError(
                f"Tracking rule {tracking_rule_id} is disabled. "
                "Enable it first or run without --rule-id to process enabled rules."
            )
        rules = [rule]
    else:
        rules = list_tracking_rules(conn, enabled=True)

    if not rules:
        return report

    provider = create_provider(cfg.agent, app_config=cfg)

    for rule in rules:
        report.rules_processed += 1
        query = _rule_to_arxiv_query(rule.rule_type, rule.query)
        candidates = arxiv_search(query, max_results=limit)
        for paper in candidates:
            _process_candidate(conn, provider, rule=rule, paper=paper, report=report)

    conn.commit()
    return report
