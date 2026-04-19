"""Tests for tracking.runner."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

from artimanager.config import AppConfig, AgentConfig
from artimanager.discovery._models import ExternalPaper
from artimanager.search.query import SearchResult
from artimanager.tracking.manager import (
    create_tracking_rule,
    serialize_openalex_author_tracking_query,
    serialize_citation_tracking_query,
)
from artimanager.tracking.runner import run_tracking


class _Provider:
    @property
    def provider_id(self) -> str:
        return "mock"

    def summarize(self, text: str) -> str:
        return f"SUMMARY::{text[:20]}"

    def analyze(self, paper: dict, prompt: str) -> str:
        return ""

    def compare(self, papers: list[dict], prompt: str) -> str:
        return ""

    def search_query(self, topic: str) -> list[str]:
        return []


class _ProviderSummaryFail(_Provider):
    def summarize(self, text: str) -> str:
        if "bad" in text:
            raise RuntimeError("summary failed")
        return super().summarize(text)


class _ProviderBadSummary(_Provider):
    def summarize(self, text: str) -> str:
        return (
            "I'd be happy to summarize that, but I don't see any text provided "
            "beyond your description of the topic. Could you paste the full text "
            "you'd like me to summarize?"
        )


class _CountingProvider(_Provider):
    def __init__(self) -> None:
        self.summarize_count = 0

    def summarize(self, text: str) -> str:
        self.summarize_count += 1
        return super().summarize(text)


def _paper(
    *,
    external_id: str,
    title: str = "Paper",
    abstract: str = "Abstract",
) -> ExternalPaper:
    return ExternalPaper(
        title=title,
        authors=["A"],
        year=2024,
        abstract=abstract,
        arxiv_id=external_id,
        source="arxiv",
        external_id=external_id,
    )


def _cfg() -> AppConfig:
    return AppConfig(agent=AgentConfig(provider="mock", model="m"))


def _insert_anchor_paper(
    conn: sqlite3.Connection,
    *,
    paper_id: str = "p1",
    doi: str | None = "10.1234/anchor",
    arxiv_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO papers (paper_id, title, doi, arxiv_id, workflow_status) "
        "VALUES (?, 'Anchor', ?, ?, 'inbox')",
        (paper_id, doi, arxiv_id),
    )


def _citation_rule(
    conn: sqlite3.Connection,
    *,
    paper_id: str = "p1",
    direction: str = "cited_by",
    limit: int = 20,
):
    query = serialize_citation_tracking_query(
        conn,
        paper_id=paper_id,
        direction=direction,
        limit=limit,
    )
    return create_tracking_rule(
        conn,
        name="Citation watch",
        rule_type="citation",
        query=query,
    )


def _openalex_author_rule(
    conn: sqlite3.Connection,
    *,
    author_id: str = "A123456789",
    limit: int = 20,
):
    query = serialize_openalex_author_tracking_query(
        author_id=author_id,
        display_name="Alice Smith",
        limit=limit,
    )
    return create_tracking_rule(
        conn,
        name="OpenAlex author",
        rule_type="openalex_author",
        query=query,
    )


def test_keyword_rule_maps_to_all_query(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[] ) as mock_search:
            run_tracking(db_conn, _cfg())
    assert mock_search.call_args[0][0] == "all:graph"


def test_author_rule_maps_to_author_query(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="a", rule_type="author", query="Alice Smith")
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[] ) as mock_search:
            run_tracking(db_conn, _cfg())
    assert mock_search.call_args[0][0] == 'au:"Alice Smith"'


def test_category_rule_maps_to_category_query(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="c", rule_type="category", query="cs.AI")
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[] ) as mock_search:
            run_tracking(db_conn, _cfg())
    assert mock_search.call_args[0][0] == "cat:cs.AI"


def test_tracking_run_stores_trigger_type_and_ref(db_conn: sqlite3.Connection) -> None:
    rule = create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[_paper(external_id="2401.00001")]):
            report = run_tracking(db_conn, _cfg())
    assert report.new_count == 1
    row = db_conn.execute(
        "SELECT trigger_type, trigger_ref, source FROM discovery_results"
    ).fetchone()
    assert tuple(row) == ("tracking_rule", rule.tracking_rule_id, "arxiv")
    source_row = db_conn.execute(
        """
        SELECT trigger_type, trigger_ref, tracking_rule_id, source, source_external_id
        FROM discovery_result_sources
        """
    ).fetchone()
    assert tuple(source_row) == (
        "tracking_rule",
        rule.tracking_rule_id,
        rule.tracking_rule_id,
        "arxiv",
        "2401.00001",
    )


def test_repeated_runs_deduplicate(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    papers = [_paper(external_id="2401.00001")]
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=papers):
            r1 = run_tracking(db_conn, _cfg())
            r2 = run_tracking(db_conn, _cfg())
    assert r1.new_count == 1
    assert r2.duplicate_count == 1
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert source_count == 1


def test_tracking_provenance_does_not_add_summary_calls(db_conn: sqlite3.Connection) -> None:
    provider = _CountingProvider()
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    with patch("artimanager.tracking.runner.create_provider", return_value=provider):
        with patch(
            "artimanager.tracking.runner.arxiv_search",
            return_value=[_paper(external_id="2401.00001", abstract="hello world")],
        ):
            run_tracking(db_conn, _cfg())

    assert provider.summarize_count == 1
    row = db_conn.execute(
        "SELECT relevance_context FROM discovery_result_sources WHERE source_external_id = '2401.00001'"
    ).fetchone()
    assert "Summary: SUMMARY::hello world" in row[0]


def test_citation_tracking_with_doi_anchor_calls_semantic_scholar(
    db_conn: sqlite3.Connection,
) -> None:
    _insert_anchor_paper(db_conn, doi="10.1234/anchor")
    rule = _citation_rule(db_conn, direction="cited_by", limit=50)
    candidate = _paper(external_id="S2-CITE", title="Citing Paper", abstract="")

    with patch("artimanager.tracking.runner.create_provider") as mock_provider:
        with patch(
            "artimanager.tracking.runner.s2_get_citations",
            return_value=[candidate],
        ) as mock_citations:
            report = run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id, limit=10)

    mock_provider.assert_not_called()
    mock_citations.assert_called_once_with("DOI:10.1234/anchor", limit=10)
    assert report.new_count == 1
    row = db_conn.execute(
        """
        SELECT direction, anchor_paper_id, anchor_external_id, source, source_external_id
        FROM discovery_result_sources
        """
    ).fetchone()
    assert tuple(row) == ("cited_by", "p1", "DOI:10.1234/anchor", "semantic_scholar", "S2-CITE")


def test_citation_tracking_with_arxiv_anchor_calls_semantic_scholar(
    db_conn: sqlite3.Connection,
) -> None:
    _insert_anchor_paper(db_conn, doi=None, arxiv_id="2401.00001v3")
    rule = _citation_rule(db_conn, direction="references")

    with patch("artimanager.tracking.runner.create_provider") as mock_provider:
        with patch(
            "artimanager.tracking.runner.s2_get_references",
            return_value=[_paper(external_id="S2-REF", abstract="")],
        ) as mock_references:
            report = run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id)

    mock_provider.assert_not_called()
    mock_references.assert_called_once_with("ARXIV:2401.00001", limit=20)
    assert report.new_count == 1
    row = db_conn.execute(
        "SELECT direction, anchor_external_id FROM discovery_result_sources"
    ).fetchone()
    assert tuple(row) == ("references", "ARXIV:2401.00001")


def test_citation_tracking_stores_candidate_with_only_paper_id(
    db_conn: sqlite3.Connection,
) -> None:
    _insert_anchor_paper(db_conn)
    rule = _citation_rule(db_conn)
    candidate = ExternalPaper(
        title="S2 Only",
        authors=["A"],
        year=2025,
        abstract="",
        source="semantic_scholar",
        external_id="S2ONLY",
    )

    with patch("artimanager.tracking.runner.s2_get_citations", return_value=[candidate]):
        report = run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id)

    assert report.new_count == 1
    row = db_conn.execute(
        "SELECT source, external_id, doi, arxiv_id FROM discovery_results"
    ).fetchone()
    assert tuple(row) == ("semantic_scholar", "S2ONLY", None, None)


def test_repeated_citation_run_deduplicates_provenance(
    db_conn: sqlite3.Connection,
) -> None:
    _insert_anchor_paper(db_conn)
    rule = _citation_rule(db_conn)
    candidate = _paper(external_id="S2-CITE", abstract="")

    with patch("artimanager.tracking.runner.s2_get_citations", return_value=[candidate]):
        first = run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id)
        second = run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id)

    assert first.new_count == 1
    assert second.duplicate_count == 1
    candidate_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert candidate_count == 1
    assert source_count == 1


def test_openalex_author_tracking_stores_candidates_and_provenance(
    db_conn: sqlite3.Connection,
) -> None:
    rule = _openalex_author_rule(db_conn, limit=50)
    candidate = ExternalPaper(
        title="OpenAlex Work",
        authors=["Alice Smith"],
        year=2026,
        abstract="",
        doi="10.1234/work",
        arxiv_id="2601.00001",
        source="openalex",
        external_id="https://openalex.org/W123",
    )

    with patch("artimanager.tracking.runner.create_provider") as mock_provider:
        with patch(
            "artimanager.tracking.runner.get_works_by_author",
            return_value=[candidate],
        ) as mock_works:
            report = run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id, limit=10)

    mock_provider.assert_not_called()
    mock_works.assert_called_once_with("https://openalex.org/A123456789", limit=10)
    assert report.new_count == 1
    result = db_conn.execute(
        "SELECT source, external_id, doi, arxiv_id FROM discovery_results"
    ).fetchone()
    assert tuple(result) == (
        "openalex",
        "https://openalex.org/W123",
        "10.1234/work",
        "2601.00001",
    )
    provenance = db_conn.execute(
        """
        SELECT source, direction, anchor_author_id, source_external_id
        FROM discovery_result_sources
        """
    ).fetchone()
    assert tuple(provenance) == (
        "openalex",
        "openalex_author_work",
        "https://openalex.org/A123456789",
        "https://openalex.org/W123",
    )


def test_repeated_openalex_author_run_deduplicates_provenance(
    db_conn: sqlite3.Connection,
) -> None:
    rule = _openalex_author_rule(db_conn)
    candidate = ExternalPaper(
        title="OpenAlex Work",
        authors=["Alice Smith"],
        year=2026,
        abstract="",
        source="openalex",
        external_id="https://openalex.org/W123",
    )

    with patch("artimanager.tracking.runner.get_works_by_author", return_value=[candidate]):
        first = run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id)
        second = run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id)

    assert first.new_count == 1
    assert second.duplicate_count == 1
    candidate_count = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_count = db_conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    assert candidate_count == 1
    assert source_count == 1


def test_summaries_written_to_relevance_context(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[_paper(external_id="2401.00001", abstract="hello world")]):
            run_tracking(db_conn, _cfg())
    row = db_conn.execute(
        "SELECT relevance_context FROM discovery_results WHERE external_id = '2401.00001'"
    ).fetchone()
    assert "Summary: SUMMARY::hello world" in row[0]


def test_normal_summary_remains_in_relevance_context(db_conn: sqlite3.Connection) -> None:
    class _ProviderNormal(_Provider):
        def summarize(self, text: str) -> str:
            return "This is a concise useful summary."

    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    with patch("artimanager.tracking.runner.create_provider", return_value=_ProviderNormal()):
        with patch(
            "artimanager.tracking.runner.arxiv_search",
            return_value=[_paper(external_id="2401.00001", abstract="hello world")],
        ):
            report = run_tracking(db_conn, _cfg())

    assert report.warning_count == 0
    row = db_conn.execute(
        "SELECT relevance_context FROM discovery_results WHERE external_id = '2401.00001'"
    ).fetchone()
    assert "Summary: This is a concise useful summary." in row[0]


def test_bad_summary_is_counted_as_warning_and_not_persisted(
    db_conn: sqlite3.Connection,
) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    bad_text = "Could you paste the full text you'd like me to summarize?"
    with patch("artimanager.tracking.runner.create_provider", return_value=_ProviderBadSummary()):
        with patch(
            "artimanager.tracking.runner.arxiv_search",
            return_value=[_paper(external_id="2401.00001", abstract="hello world")],
        ):
            report = run_tracking(db_conn, _cfg())

    assert report.warning_count == 1
    row = db_conn.execute(
        "SELECT relevance_context FROM discovery_results WHERE external_id = '2401.00001'"
    ).fetchone()
    assert "Summary unavailable: provider did not return a usable summary" in row[0]
    assert bad_text not in row[0]


def test_relevance_score_populated_from_local_context(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    local_hits = [
        SearchResult(
            paper_id="p1",
            title="Graph Neural Network Methods",
            authors=["A"],
            year=2024,
            match_source="metadata",
            snippet="",
            score=1.0,
        )
    ]
    with patch("artimanager.tracking.runner.search_all", return_value=local_hits):
        with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
            with patch("artimanager.tracking.runner.arxiv_search", return_value=[_paper(external_id="2401.00001", title="Graph Methods")]):
                run_tracking(db_conn, _cfg())
    row = db_conn.execute(
        "SELECT relevance_score FROM discovery_results WHERE external_id = '2401.00001'"
    ).fetchone()
    assert row[0] is not None
    assert row[0] > 0


def test_zero_title_overlap_does_not_list_local_query_hits(
    db_conn: sqlite3.Connection,
) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    local_hits = [
        SearchResult(
            paper_id="p1",
            title="Graph Neural Network Methods",
            authors=["A"],
            year=2024,
            match_source="metadata",
            snippet="",
            score=1.0,
        )
    ]
    with patch("artimanager.tracking.runner.search_all", return_value=local_hits):
        with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
            with patch(
                "artimanager.tracking.runner.arxiv_search",
                return_value=[_paper(external_id="2401.00001", title="Quantum Sensors")],
            ):
                run_tracking(db_conn, _cfg())
    row = db_conn.execute(
        "SELECT relevance_score, relevance_context FROM discovery_results WHERE external_id = '2401.00001'"
    ).fetchone()
    assert row[0] == 0.0
    assert "Local title-overlap matches:" in row[1]
    assert "p1: Graph Neural Network Methods" not in row[1]
    assert "- (none)" in row[1]


def test_disabled_rules_are_skipped(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph", enabled=False)
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[]) as mock_search:
            report = run_tracking(db_conn, _cfg())
    assert report.rules_processed == 0
    assert mock_search.call_count == 0


def test_rule_id_limits_execution(db_conn: sqlite3.Connection) -> None:
    r1 = create_tracking_rule(db_conn, name="k1", rule_type="keyword", query="graph")
    create_tracking_rule(db_conn, name="k2", rule_type="keyword", query="vision")
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[]) as mock_search:
            report = run_tracking(db_conn, _cfg(), tracking_rule_id=r1.tracking_rule_id)
    assert report.rules_processed == 1
    assert mock_search.call_count == 1
    assert mock_search.call_args[0][0] == "all:graph"


def test_summarize_failure_does_not_abort_rule(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    papers = [
        _paper(external_id="2401.00001", abstract="bad abstract"),
        _paper(external_id="2401.00002", abstract="good abstract"),
    ]
    with patch("artimanager.tracking.runner.create_provider", return_value=_ProviderSummaryFail()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=papers):
            report = run_tracking(db_conn, _cfg())
    assert report.new_count == 2
    assert report.error_count == 0
    assert report.warning_count == 1
    # total should remain mutually consistent with candidate outcomes
    assert report.total == report.new_count + report.duplicate_count + report.error_count
    row = db_conn.execute(
        "SELECT relevance_context FROM discovery_results WHERE external_id = '2401.00001'"
    ).fetchone()
    assert "Summary generation failed" in row[0]


def test_rule_id_disabled_rule_raises_clear_error(db_conn: sqlite3.Connection) -> None:
    rule = create_tracking_rule(
        db_conn,
        name="k",
        rule_type="keyword",
        query="graph",
        enabled=False,
    )
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[]):
            try:
                run_tracking(db_conn, _cfg(), tracking_rule_id=rule.tracking_rule_id)
                assert False, "Expected ValueError for disabled explicit rule"
            except ValueError as exc:
                assert "disabled" in str(exc)
