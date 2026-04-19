"""Tracking runner for Phase 9 (CLI-invoked scheduled fetch)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from artimanager.agent.factory import create_provider
from artimanager.config import AppConfig
from artimanager.db.utils import new_id
from artimanager.discovery._models import ExternalPaper
from artimanager.discovery.arxiv_api import search as arxiv_search
from artimanager.discovery.engine import DiscoveryRecord
from artimanager.discovery.openalex_api import get_works_by_author
from artimanager.discovery.provenance import (
    DiscoverySourceContext,
    store_discovery_record_with_source,
)
from artimanager.discovery.semantic_scholar import (
    get_citations as s2_get_citations,
    get_references as s2_get_references,
    semantic_scholar_identifier_for_arxiv,
    semantic_scholar_identifier_for_doi,
)
from artimanager.search.query import search_all
from artimanager.tracking.manager import (
    CitationTrackingPayload,
    OpenAlexAuthorTrackingPayload,
    get_tracking_rule,
    list_tracking_rules,
    parse_citation_tracking_query,
    parse_openalex_author_tracking_query,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_UNUSABLE_SUMMARY_PATTERNS = (
    "i don't see any text provided",
    "could you paste the full text",
    "please provide the text",
    "provide the text you'd like me to summarize",
)


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
    candidate_tokens = _tokenize(candidate_title)
    if not candidate_tokens:
        return 0.0, []

    local_titles: list[tuple[str, str]] = []
    local_tokens: set[str] = set()
    for item in local_matches:
        title_tokens = _tokenize(item.title)
        overlap = candidate_tokens & title_tokens
        if not overlap:
            continue
        local_tokens.update(overlap)
        local_titles.append((item.paper_id, item.title))
        if len(local_titles) >= 3:
            break

    if not candidate_tokens or not local_tokens:
        return 0.0, []
    score = len(candidate_tokens & local_tokens) / len(candidate_tokens)
    return float(score), local_titles


def _clean_summary_output(summary: str) -> str | None:
    cleaned = " ".join((summary or "").split()).strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(pattern in lowered for pattern in _UNUSABLE_SUMMARY_PATTERNS):
        return None
    return cleaned


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
        "Local title-overlap matches:",
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


def _to_citation_discovery_record(
    paper: ExternalPaper,
    *,
    tracking_rule_id: str,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        discovery_result_id=new_id(),
        trigger_type="tracking_rule",
        trigger_ref=tracking_rule_id,
        source="semantic_scholar",
        external_id=paper.external_id,
        title=paper.title,
        authors=paper.authors,
        abstract=paper.abstract,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        published_at=str(paper.year) if paper.year is not None else None,
        relevance_score=None,
        relevance_context=None,
        status="new",
        review_action=None,
        imported_paper_id=None,
    )


def _to_openalex_discovery_record(
    paper: ExternalPaper,
    *,
    tracking_rule_id: str,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        discovery_result_id=new_id(),
        trigger_type="tracking_rule",
        trigger_ref=tracking_rule_id,
        source="openalex",
        external_id=paper.external_id,
        title=paper.title,
        authors=paper.authors,
        abstract=paper.abstract,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        published_at=str(paper.year) if paper.year is not None else None,
        relevance_score=None,
        relevance_context=None,
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
            cleaned = _clean_summary_output(summary)
            if cleaned is None:
                summary = "Summary unavailable: provider did not return a usable summary"
                report.warning_count += 1
            else:
                summary = cleaned
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
    context = DiscoverySourceContext(
        trigger_type="tracking_rule",
        trigger_ref=rule.tracking_rule_id,
        tracking_rule_id=rule.tracking_rule_id,
        source="arxiv",
        source_external_id=record.external_id,
        relevance_score=relevance_score,
        relevance_context=relevance_context,
    )
    outcome = store_discovery_record_with_source(conn, record, context)
    if outcome.candidate_inserted:
        report.new_count += 1
        report.records.append(record)
    else:
        report.duplicate_count += 1


def _resolve_citation_anchor(
    conn,
    payload: CitationTrackingPayload,
) -> str:
    row = conn.execute(
        "SELECT doi, arxiv_id FROM papers WHERE paper_id = ?",
        (payload.paper_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Paper not found for citation tracking: {payload.paper_id}")
    doi, arxiv_id = row[0], row[1]
    if doi:
        return semantic_scholar_identifier_for_doi(doi)
    if arxiv_id:
        return semantic_scholar_identifier_for_arxiv(arxiv_id)
    raise ValueError(
        f"Paper {payload.paper_id} has neither DOI nor arXiv ID for citation tracking"
    )


def _process_citation_candidate(
    conn,
    *,
    rule,
    payload: CitationTrackingPayload,
    anchor_identifier: str,
    paper: ExternalPaper,
    report: TrackingRunReport,
) -> None:
    if not paper.external_id and not paper.doi and not paper.arxiv_id:
        report.error_count += 1
        return

    record = _to_citation_discovery_record(
        paper,
        tracking_rule_id=rule.tracking_rule_id,
    )
    context = DiscoverySourceContext(
        trigger_type="tracking_rule",
        trigger_ref=rule.tracking_rule_id,
        tracking_rule_id=rule.tracking_rule_id,
        source="semantic_scholar",
        direction=payload.direction,
        anchor_paper_id=payload.paper_id,
        anchor_external_id=anchor_identifier,
        source_external_id=record.external_id,
    )
    outcome = store_discovery_record_with_source(conn, record, context)
    if outcome.candidate_inserted:
        report.new_count += 1
        report.records.append(record)
    else:
        report.duplicate_count += 1


def _process_citation_rule(
    conn,
    *,
    rule,
    report: TrackingRunReport,
    runtime_limit: int,
) -> None:
    payload = parse_citation_tracking_query(rule.query)
    anchor_identifier = _resolve_citation_anchor(conn, payload)
    effective_limit = min(runtime_limit, payload.limit)
    if payload.direction == "cited_by":
        candidates = s2_get_citations(anchor_identifier, limit=effective_limit)
    else:
        candidates = s2_get_references(anchor_identifier, limit=effective_limit)

    for paper in candidates:
        _process_citation_candidate(
            conn,
            rule=rule,
            payload=payload,
            anchor_identifier=anchor_identifier,
            paper=paper,
            report=report,
        )


def _process_openalex_author_candidate(
    conn,
    *,
    rule,
    payload: OpenAlexAuthorTrackingPayload,
    paper: ExternalPaper,
    report: TrackingRunReport,
) -> None:
    if not paper.external_id and not paper.doi and not paper.arxiv_id:
        report.error_count += 1
        return

    record = _to_openalex_discovery_record(
        paper,
        tracking_rule_id=rule.tracking_rule_id,
    )
    context = DiscoverySourceContext(
        trigger_type="tracking_rule",
        trigger_ref=rule.tracking_rule_id,
        tracking_rule_id=rule.tracking_rule_id,
        source="openalex",
        direction="openalex_author_work",
        anchor_author_id=payload.author_id,
        source_external_id=record.external_id,
    )
    outcome = store_discovery_record_with_source(conn, record, context)
    if outcome.candidate_inserted:
        report.new_count += 1
        report.records.append(record)
    else:
        report.duplicate_count += 1


def _process_openalex_author_rule(
    conn,
    *,
    rule,
    report: TrackingRunReport,
    runtime_limit: int,
) -> None:
    payload = parse_openalex_author_tracking_query(rule.query)
    effective_limit = min(runtime_limit, payload.limit)
    candidates = get_works_by_author(payload.author_id, limit=effective_limit)
    for paper in candidates:
        _process_openalex_author_candidate(
            conn,
            rule=rule,
            payload=payload,
            paper=paper,
            report=report,
        )


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

    provider = None

    for rule in rules:
        report.rules_processed += 1
        if rule.rule_type == "citation":
            _process_citation_rule(
                conn,
                rule=rule,
                report=report,
                runtime_limit=limit,
            )
            continue
        if rule.rule_type == "openalex_author":
            _process_openalex_author_rule(
                conn,
                rule=rule,
                report=report,
                runtime_limit=limit,
            )
            continue
        if provider is None:
            provider = create_provider(cfg.agent, app_config=cfg)
        query = _rule_to_arxiv_query(rule.rule_type, rule.query)
        candidates = arxiv_search(query, max_results=limit)
        for paper in candidates:
            _process_candidate(conn, provider, rule=rule, paper=paper, report=report)

    conn.commit()
    return report
