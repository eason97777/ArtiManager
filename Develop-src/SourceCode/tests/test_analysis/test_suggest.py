"""Tests for analysis.suggest."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from artimanager.analysis.suggest import suggest_follow_up_work, suggest_related_work
from artimanager.config import AgentOverrideConfig, AppConfig
from artimanager.relationships.manager import create_relationship


def _insert_paper(
    conn: sqlite3.Connection,
    paper_id: str,
    title: str,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO papers (paper_id, title, authors, abstract, doi, arxiv_id, workflow_status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'inbox')",
        (paper_id, title, json.dumps(["A"]), "Abs", doi, arxiv_id),
    )
    conn.commit()


def _insert_discovery_result(
    conn: sqlite3.Connection,
    *,
    result_id: str,
    anchor_id: str,
    imported_paper_id: str,
) -> None:
    conn.execute(
        "INSERT INTO discovery_results "
        "(discovery_result_id, trigger_type, trigger_ref, source, external_id, status, imported_paper_id) "
        "VALUES (?, 'paper_anchor', ?, 'semantic_scholar', ?, 'imported', ?)",
        (result_id, anchor_id, result_id, imported_paper_id),
    )
    conn.commit()


class _ProviderTSV:
    def __init__(self, output: str) -> None:
        self.output = output
        self.compare_calls = 0

    @property
    def provider_id(self) -> str:
        return "mock"

    def analyze(self, paper: dict, prompt: str) -> str:
        return ""

    def compare(self, papers: list[dict], prompt: str) -> str:
        self.compare_calls += 1
        return self.output

    def search_query(self, topic: str) -> list[str]:
        return []

    def summarize(self, text: str) -> str:
        return text


def test_candidate_set_includes_discovery_imports(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor")
    _insert_paper(db_conn, "p2", "Discovered")
    _insert_discovery_result(db_conn, result_id="dr1", anchor_id="p1", imported_paper_id="p2")

    provider = _ProviderTSV("p2\t0.80\tdiscovery-match")
    with patch("artimanager.analysis.suggest.create_provider", return_value=provider):
        record, rels = suggest_related_work(db_conn, sample_config, "p1")

    assert record.analysis_type == "related_work_suggestion"
    assert len(rels) == 1
    assert rels[0].target_paper_id == "p2"


def test_candidate_set_includes_metadata_matches(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor", doi="10.1234/aaa")
    _insert_paper(db_conn, "p2", "Candidate", doi="10.1234/bbb")

    provider = _ProviderTSV("p2\t0.70\tdoi-prefix")
    with patch("artimanager.analysis.suggest.create_provider", return_value=provider):
        _, rels = suggest_related_work(db_conn, sample_config, "p1")

    assert len(rels) == 1
    assert rels[0].target_paper_id == "p2"


def test_existing_relationships_are_excluded(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor")
    _insert_paper(db_conn, "p2", "Candidate")
    create_relationship(db_conn, "p1", "p2", "prior_work", status="confirmed")

    provider = _ProviderTSV("p2\t0.90\talready-related")
    with patch("artimanager.analysis.suggest.create_provider", return_value=provider):
        _, rels = suggest_related_work(
            db_conn, sample_config, "p1", candidate_paper_ids=["p2"],
        )

    assert rels == []


def test_self_reference_is_excluded(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor")
    _insert_paper(db_conn, "p2", "Candidate")

    provider = _ProviderTSV("p1\t0.80\tself\np2\t0.75\tvalid")
    with patch("artimanager.analysis.suggest.create_provider", return_value=provider):
        _, rels = suggest_related_work(
            db_conn, sample_config, "p1", candidate_paper_ids=["p1", "p2"],
        )

    assert len(rels) == 1
    assert rels[0].target_paper_id == "p2"


def test_related_mode_creates_prior_work_agent_inferred(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor")
    _insert_paper(db_conn, "p2", "Candidate")

    provider = _ProviderTSV("p2\t0.60\trelated reason")
    with patch("artimanager.analysis.suggest.create_provider", return_value=provider):
        _, rels = suggest_related_work(
            db_conn, sample_config, "p1", candidate_paper_ids=["p2"],
        )

    assert len(rels) == 1
    rel = rels[0]
    assert rel.relationship_type == "prior_work"
    assert rel.evidence_type == "agent_inferred"
    assert rel.created_by == "analysis_pipeline"
    assert rel.status == "suggested"


def test_follow_up_mode_creates_follow_up_agent_inferred(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor")
    _insert_paper(db_conn, "p2", "Candidate")

    provider = _ProviderTSV("p2\t0.66\tfollow-up reason")
    with patch("artimanager.analysis.suggest.create_provider", return_value=provider):
        _, rels = suggest_follow_up_work(
            db_conn, sample_config, "p1", candidate_paper_ids=["p2"],
        )

    assert len(rels) == 1
    rel = rels[0]
    assert rel.relationship_type == "follow_up_work"
    assert rel.evidence_type == "agent_inferred"
    assert rel.created_by == "analysis_pipeline"
    assert rel.status == "suggested"


def test_malformed_lines_are_ignored_and_logged_in_artifact(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor")
    _insert_paper(db_conn, "p2", "Candidate")

    provider = _ProviderTSV(
        "bad-line\n"
        "p2\tnot-a-float\treason\n"
        "p2\t0.77\tvalid-reason\n"
        "unknown\t0.6\tout-of-set\n"
    )
    with patch("artimanager.analysis.suggest.create_provider", return_value=provider):
        record, rels = suggest_related_work(
            db_conn, sample_config, "p1", candidate_paper_ids=["p2"],
        )

    assert len(rels) == 1
    assert record.content_location is not None
    text = Path(record.content_location).read_text()
    assert "## Skipped Lines" in text
    assert "bad-line" in text


def test_empty_candidate_set_still_creates_analysis_record(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor")

    provider = _ProviderTSV("p2\t0.7\tno-op")
    with patch("artimanager.analysis.suggest.create_provider", return_value=provider):
        record, rels = suggest_related_work(db_conn, sample_config, "p1")

    assert record.analysis_type == "related_work_suggestion"
    assert rels == []
    assert provider.compare_calls == 0


def test_partial_analysis_override_is_merged_in_suggest_layer(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Anchor")
    _insert_paper(db_conn, "p2", "Candidate")
    sample_config.agent.provider = "mock"
    sample_config.agent.model = "root-model"
    sample_config.agent.api_key_env = "ROOT_KEY"
    sample_config.agent.overrides.analysis = AgentOverrideConfig(api_key_env="ANALYSIS_KEY")

    captured: dict[str, str] = {}
    provider = _ProviderTSV("p2\t0.9\treason")

    def _fake_create_provider(agent_cfg, **kwargs):
        captured["provider"] = agent_cfg.provider
        captured["model"] = agent_cfg.model
        captured["api_key_env"] = agent_cfg.api_key_env
        return provider

    with patch(
        "artimanager.analysis.suggest.create_provider",
        side_effect=_fake_create_provider,
    ):
        _, rels = suggest_related_work(
            db_conn, sample_config, "p1", candidate_paper_ids=["p2"],
        )

    assert len(rels) == 1
    assert captured["provider"] == "mock"
    assert captured["model"] == "root-model"
    assert captured["api_key_env"] == "ANALYSIS_KEY"
