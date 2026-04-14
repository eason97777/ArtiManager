"""Tests for tracking.runner."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

from artimanager.config import AppConfig, AgentConfig
from artimanager.discovery._models import ExternalPaper
from artimanager.search.query import SearchResult
from artimanager.tracking.manager import create_tracking_rule
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


def test_repeated_runs_deduplicate(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    papers = [_paper(external_id="2401.00001")]
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=papers):
            r1 = run_tracking(db_conn, _cfg())
            r2 = run_tracking(db_conn, _cfg())
    assert r1.new_count == 1
    assert r2.duplicate_count == 1


def test_summaries_written_to_relevance_context(db_conn: sqlite3.Connection) -> None:
    create_tracking_rule(db_conn, name="k", rule_type="keyword", query="graph")
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[_paper(external_id="2401.00001", abstract="hello world")]):
            run_tracking(db_conn, _cfg())
    row = db_conn.execute(
        "SELECT relevance_context FROM discovery_results WHERE external_id = '2401.00001'"
    ).fetchone()
    assert "Summary: SUMMARY::hello world" in row[0]


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
