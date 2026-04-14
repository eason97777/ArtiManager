"""Tests for discovery.engine — orchestration, dedup, and storage."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from artimanager.config import DeepXivConfig
from artimanager.discovery._models import ExternalPaper
from artimanager.discovery.engine import (
    DiscoveryRecord,
    run_discovery,
)


def _make_external_paper(
    title: str = "External Paper",
    doi: str | None = "10.9999/ext",
    arxiv_id: str | None = None,
    source: str = "semantic_scholar",
) -> ExternalPaper:
    ext_id = doi or arxiv_id or ""
    return ExternalPaper(
        title=title,
        authors=["Author A"],
        year=2023,
        abstract="An abstract.",
        doi=doi,
        arxiv_id=arxiv_id,
        source=source,
        external_id=ext_id,
        citation_count=5,
    )


def _insert_paper(
    conn: sqlite3.Connection,
    paper_id: str = "p1",
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO papers (paper_id, title, doi, arxiv_id, workflow_status)
           VALUES (?, ?, ?, ?, 'inbox')""",
        (paper_id, "Test Paper", doi, arxiv_id),
    )


class TestRunDiscoveryTopic:
    """Topic-anchored discovery."""

    @patch("artimanager.discovery.engine.s2_search")
    def test_topic_s2_new_results(self, mock_s2, db_conn: sqlite3.Connection) -> None:
        mock_s2.return_value = [
            _make_external_paper("Paper A", doi="10.9999/a"),
            _make_external_paper("Paper B", doi="10.9999/b"),
        ]
        report = run_discovery(db_conn, topic="test topic", source="semantic_scholar")
        assert report.new_count == 2
        assert report.duplicate_count == 0

        rows = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()
        assert rows[0] == 2

    @patch("artimanager.discovery.engine.s2_search")
    def test_topic_dedup(self, mock_s2, db_conn: sqlite3.Connection) -> None:
        mock_s2.return_value = [
            _make_external_paper("Paper A", doi="10.9999/a"),
        ]
        r1 = run_discovery(db_conn, topic="test", source="semantic_scholar")
        assert r1.new_count == 1

        r2 = run_discovery(db_conn, topic="test", source="semantic_scholar")
        assert r2.duplicate_count == 1
        assert r2.new_count == 0

    @patch("artimanager.discovery.engine.deepxiv_search")
    def test_topic_deepxiv_new_results(
        self,
        mock_deepxiv,
        db_conn: sqlite3.Connection,
    ) -> None:
        mock_deepxiv.return_value = [
            _make_external_paper(
                "DeepXiv Paper",
                doi="10.9999/dx",
                source="deepxiv_arxiv",
            ),
        ]
        cfg = DeepXivConfig(enabled=True, api_token_env="DEEPXIV_TOKEN")
        report = run_discovery(
            db_conn,
            topic="gnn",
            source="deepxiv",
            deepxiv_config=cfg,
        )
        assert report.new_count == 1
        assert report.duplicate_count == 0
        mock_deepxiv.assert_called_once_with("gnn", cfg, limit=20)

    def test_topic_deepxiv_requires_config(self, db_conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="DeepXiv config is required"):
            run_discovery(db_conn, topic="gnn", source="deepxiv")

    @patch("artimanager.discovery.engine.deepxiv_search")
    @patch("artimanager.discovery.engine.arxiv_search")
    @patch("artimanager.discovery.engine.s2_search")
    def test_source_all_unchanged_does_not_call_deepxiv(
        self,
        mock_s2,
        mock_arxiv,
        mock_deepxiv,
        db_conn: sqlite3.Connection,
    ) -> None:
        mock_s2.return_value = [_make_external_paper("S2", doi="10.1111/a")]
        mock_arxiv.return_value = [
            _make_external_paper("Arxiv", doi="10.1111/b", source="arxiv"),
        ]
        report = run_discovery(db_conn, topic="test", source="all")
        assert report.new_count == 2
        assert report.error_count == 0
        mock_deepxiv.assert_not_called()

    @patch("artimanager.discovery.engine.arxiv_search")
    @patch("artimanager.discovery.engine.s2_search")
    def test_cross_source_dedup_prefers_doi(
        self,
        mock_s2,
        mock_arxiv,
        db_conn: sqlite3.Connection,
    ) -> None:
        mock_s2.return_value = [
            _make_external_paper("S2 Paper", doi="10.1111/shared"),
        ]
        mock_arxiv.return_value = [
            _make_external_paper(
                "Arxiv Paper",
                doi="10.1111/shared",
                arxiv_id="2401.00001",
                source="arxiv",
            ),
        ]
        report = run_discovery(db_conn, topic="test", source="all")
        assert report.new_count == 1
        assert report.duplicate_count == 1
        row = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()
        assert row[0] == 1

    @patch("artimanager.discovery.engine.arxiv_search")
    @patch("artimanager.discovery.engine.s2_search")
    def test_cross_source_dedup_falls_back_to_arxiv_id(
        self,
        mock_s2,
        mock_arxiv,
        db_conn: sqlite3.Connection,
    ) -> None:
        mock_s2.return_value = [
            _make_external_paper(
                "S2 Paper",
                doi=None,
                arxiv_id="2401.00002",
                source="semantic_scholar",
            ),
        ]
        mock_arxiv.return_value = [
            _make_external_paper(
                "Arxiv Paper",
                doi=None,
                arxiv_id="2401.00002",
                source="arxiv",
            ),
        ]
        report = run_discovery(db_conn, topic="test", source="all")
        assert report.new_count == 1
        assert report.duplicate_count == 1
        row = db_conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()
        assert row[0] == 1


class TestRunDiscoveryPaper:
    """Paper-anchored discovery."""

    @patch("artimanager.discovery.engine.s2_by_doi")
    @patch("artimanager.discovery.engine.s2_references")
    @patch("artimanager.discovery.engine.s2_citations")
    def test_paper_references_and_citations(
        self, mock_cite, mock_ref, mock_doi, db_conn: sqlite3.Connection,
    ) -> None:
        _insert_paper(db_conn, "p1", doi="10.1234/test")
        db_conn.commit()

        mock_doi.return_value = _make_external_paper("Anchor", doi="10.1234/test")
        mock_ref.return_value = [_make_external_paper("Ref", doi="10.9999/ref")]
        mock_cite.return_value = [_make_external_paper("Cite", doi="10.9999/cite")]

        report = run_discovery(db_conn, paper_id="p1", source="semantic_scholar")
        assert report.new_count == 2
        assert report.duplicate_count == 0

    def test_paper_not_found(self, db_conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="Paper not found"):
            run_discovery(db_conn, paper_id="nonexistent")

    def test_no_external_ids(self, db_conn: sqlite3.Connection) -> None:
        _insert_paper(db_conn, "p1")
        db_conn.commit()
        with pytest.raises(ValueError, match="neither DOI nor arXiv ID"):
            run_discovery(db_conn, paper_id="p1")

    def test_deepxiv_paper_anchor_not_supported(
        self,
        db_conn: sqlite3.Connection,
    ) -> None:
        _insert_paper(db_conn, "p1", doi="10.1234/test")
        db_conn.commit()
        with pytest.raises(ValueError, match="topic-only runs"):
            run_discovery(db_conn, paper_id="p1", source="deepxiv")

    def test_neither_paper_nor_topic(self, db_conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="Either paper_id or topic"):
            run_discovery(db_conn)


class TestDiscoveryRecord:
    def test_creation(self) -> None:
        r = DiscoveryRecord(
            discovery_result_id="r1",
            trigger_type="topic_anchor",
            trigger_ref="quantum",
            source="arxiv",
            external_id="2301.12345",
            title="Test",
            authors=["A"],
            abstract="",
            published_at="2023",
            relevance_score=None,
            relevance_context=None,
        )
        assert r.status == "new"
        assert r.review_action is None


class TestDiscoveryReport:
    def test_total(self) -> None:
        from artimanager.discovery.engine import DiscoveryReport
        r = DiscoveryReport(new_count=3, duplicate_count=2, error_count=1)
        assert r.total == 6
