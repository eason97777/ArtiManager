"""Discovery orchestration — run online discovery and store results.

Coordinates API adapters, deduplicates, and persists results to the
``discovery_results`` table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from artimanager.config import DeepXivConfig
from artimanager.db.utils import new_id
from artimanager.discovery._models import ExternalPaper
from artimanager.discovery.arxiv_api import search_by_topic as arxiv_search
from artimanager.discovery.deepxiv_api import search_by_topic as deepxiv_search
from artimanager.discovery.provenance import (
    DiscoverySourceContext,
    find_existing_discovery_result_id,
    store_discovery_record_with_source,
)
from artimanager.discovery.semantic_scholar import (
    get_citations as s2_citations,
    get_paper_by_arxiv as s2_by_arxiv,
    get_paper_by_doi as s2_by_doi,
    get_references as s2_references,
    search_by_query as s2_search,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryRecord:
    """One discovery result, matching the discovery_results table."""

    discovery_result_id: str
    trigger_type: str       # "paper_anchor" | "topic_anchor"
    trigger_ref: str | None
    source: str             # "semantic_scholar" | "arxiv" | "deepxiv_arxiv"
    external_id: str
    title: str
    authors: list[str]
    abstract: str
    doi: str | None = None
    arxiv_id: str | None = None
    published_at: str | None = None
    relevance_score: float | None = None
    relevance_context: str | None = None
    status: str = "new"
    review_action: str | None = None
    imported_paper_id: str | None = None


@dataclass
class DiscoveryReport:
    """Summary of a discovery run."""

    new_count: int = 0
    duplicate_count: int = 0
    error_count: int = 0
    records: list[DiscoveryRecord] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.new_count + self.duplicate_count + self.error_count


def _resolve_paper_external_ids(
    conn,
    paper_id: str,
) -> tuple[str | None, str | None]:
    """Return (doi, arxiv_id) for a library paper."""
    row = conn.execute(
        "SELECT doi, arxiv_id FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Paper not found: {paper_id}")
    return row[0], row[1]


def _external_paper_to_record(
    paper: ExternalPaper,
    trigger_type: str,
    trigger_ref: str | None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        discovery_result_id=new_id(),
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
        source=paper.source,
        external_id=paper.external_id,
        title=paper.title,
        authors=paper.authors,
        abstract=paper.abstract,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        published_at=str(paper.year) if paper.year else None,
        relevance_score=float(paper.citation_count) if paper.citation_count else None,
        relevance_context=None,
    )


def result_exists(
    conn,
    source: str,
    external_id: str,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> bool:
    """Check dedupe identity across sources.

    Order:
    1. DOI exact match
    2. arXiv ID exact match
    3. fallback to (source, external_id)
    """
    return find_existing_discovery_result_id(
        conn,
        source=source,
        external_id=external_id,
        doi=doi,
        arxiv_id=arxiv_id,
    ) is not None


def store_discovery_record(conn, record: DiscoveryRecord) -> bool:
    """Insert a discovery record if it's not a duplicate.

    Returns ``True`` when inserted, ``False`` when skipped as duplicate.
    """
    if not record.external_id and not record.doi and not record.arxiv_id:
        return False
    context = DiscoverySourceContext(
        trigger_type=record.trigger_type,
        trigger_ref=record.trigger_ref,
        source=record.source,
        source_external_id=record.external_id,
        relevance_score=record.relevance_score,
        relevance_context=record.relevance_context,
    )
    outcome = store_discovery_record_with_source(conn, record, context)
    return outcome.candidate_inserted


def run_discovery(
    conn,
    *,
    paper_id: str | None = None,
    topic: str | None = None,
    source: str = "all",
    limit: int = 20,
    deepxiv_config: DeepXivConfig | None = None,
) -> DiscoveryReport:
    """Run online discovery and store new results.

    Parameters
    ----------
    conn:
        Open database connection.
    paper_id:
        Library paper to anchor discovery on.
    topic:
        Free-text topic/keyword to search.
    source:
        ``"semantic_scholar"``, ``"arxiv"``, or ``"all"``.
    limit:
        Max results per source.

    Returns
    -------
    DiscoveryReport summarising what was found.
    """
    if paper_id is None and topic is None:
        raise ValueError("Either paper_id or topic must be provided")

    report = DiscoveryReport()
    trigger_type = "paper_anchor" if paper_id else "topic_anchor"
    trigger_ref = paper_id or topic

    if paper_id:
        if source == "deepxiv":
            raise ValueError(
                "DeepXiv discovery in this phase supports topic-only runs; --paper-id is not supported."
            )
        doi, arxiv_id = _resolve_paper_external_ids(conn, paper_id)
        if not doi and not arxiv_id:
            raise ValueError(
                f"Paper {paper_id} has neither DOI nor arXiv ID"
            )

        # Semantic Scholar
        if source in ("all", "semantic_scholar"):
            s2_id = None
            if doi:
                paper = s2_by_doi(doi)
                if paper:
                    s2_id = paper.external_id
            if not s2_id and arxiv_id:
                paper = s2_by_arxiv(arxiv_id)
                if paper:
                    s2_id = paper.external_id

            if s2_id:
                for p in s2_references(s2_id, limit=limit):
                    _process_paper(
                        p,
                        conn,
                        report,
                        trigger_type,
                        trigger_ref,
                        direction="references",
                        anchor_paper_id=paper_id,
                        anchor_external_id=s2_id,
                    )
                for p in s2_citations(s2_id, limit=limit):
                    _process_paper(
                        p,
                        conn,
                        report,
                        trigger_type,
                        trigger_ref,
                        direction="cited_by",
                        anchor_paper_id=paper_id,
                        anchor_external_id=s2_id,
                    )
            else:
                logger.warning("Could not resolve S2 ID for paper %s", paper_id)
                report.error_count += 1

        # arXiv
        if source in ("all", "arxiv") and arxiv_id:
            results = arxiv_search(arxiv_id, max_results=limit)
            for p in results:
                _process_paper(
                    p,
                    conn,
                    report,
                    trigger_type,
                    trigger_ref,
                    anchor_paper_id=paper_id,
                    anchor_external_id=arxiv_id,
                )

    elif topic:
        if source in ("all", "semantic_scholar"):
            for p in s2_search(topic, limit=limit):
                _process_paper(p, conn, report, trigger_type, trigger_ref)

        if source in ("all", "arxiv"):
            for p in arxiv_search(topic, max_results=limit):
                _process_paper(p, conn, report, trigger_type, trigger_ref)

        if source == "deepxiv":
            if deepxiv_config is None:
                raise ValueError("DeepXiv config is required when source='deepxiv'.")
            for p in deepxiv_search(topic, deepxiv_config, limit=limit):
                _process_paper(p, conn, report, trigger_type, trigger_ref)

    conn.commit()
    return report


def _process_paper(
    paper: ExternalPaper,
    conn,
    report: DiscoveryReport,
    trigger_type: str,
    trigger_ref: str | None,
    *,
    direction: str | None = None,
    anchor_paper_id: str | None = None,
    anchor_external_id: str | None = None,
) -> None:
    if not paper.external_id and not paper.doi and not paper.arxiv_id:
        report.error_count += 1
        return

    record = _external_paper_to_record(paper, trigger_type, trigger_ref)
    context = DiscoverySourceContext(
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
        source=record.source,
        direction=direction,
        anchor_paper_id=anchor_paper_id,
        anchor_external_id=anchor_external_id,
        source_external_id=record.external_id,
        relevance_score=record.relevance_score,
        relevance_context=record.relevance_context,
    )
    outcome = store_discovery_record_with_source(conn, record, context)
    if outcome.candidate_inserted:
        report.new_count += 1
        report.records.append(record)
    else:
        report.duplicate_count += 1
