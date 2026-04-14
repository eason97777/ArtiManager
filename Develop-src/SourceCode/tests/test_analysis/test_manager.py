"""Tests for analysis.manager."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from artimanager.analysis.manager import (
    create_comparison,
    create_single_analysis,
    get_analysis,
    list_analyses,
)
from artimanager.config import AgentOverrideConfig, AppConfig


def _insert_paper(
    conn: sqlite3.Connection,
    paper_id: str,
    title: str,
    *,
    abstract: str = "Abstract",
) -> None:
    conn.execute(
        "INSERT INTO papers (paper_id, title, authors, abstract, workflow_status) "
        "VALUES (?, ?, ?, ?, 'inbox')",
        (paper_id, title, json.dumps(["A", "B"]), abstract),
    )
    conn.execute(
        "INSERT INTO file_assets (file_id, paper_id, absolute_path, filename, full_text_extracted, full_text) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (f"file-{paper_id}", paper_id, f"/tmp/{paper_id}.pdf", f"{paper_id}.pdf", "Full text"),
    )
    conn.commit()


class _ProviderGood:
    @property
    def provider_id(self) -> str:
        return "mock"

    def analyze(self, paper: dict, prompt: str) -> str:
        return "## Facts\nfact-a\nfact-b\n\n## Inference\ninference-a"

    def compare(self, papers: list[dict], prompt: str) -> str:
        return "## Facts\nfact-compare\n\n## Inference\ninference-compare"

    def search_query(self, topic: str) -> list[str]:
        return []

    def summarize(self, text: str) -> str:
        return text


class _ProviderMissingHeading(_ProviderGood):
    def analyze(self, paper: dict, prompt: str) -> str:
        return "## Facts\nfact-only"


class _ProviderExtraHeadingAfterInference(_ProviderGood):
    def analyze(self, paper: dict, prompt: str) -> str:
        return (
            "## Facts\nfact-a\n\n"
            "## Inference\ninference-a\n\n"
            "## Extra\nshould-fail"
        )


def test_create_single_analysis_record_and_artifact(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderGood()):
        record = create_single_analysis(db_conn, sample_config, "p1")

    assert record.analysis_type == "single_paper_summary"
    assert record.provider_id == "mock"
    assert record.paper_ids == ["p1"]
    assert record.prompt_version == "phase8-analysis-v1"
    assert record.fact_sections == {"Facts": "fact-a\nfact-b"}
    assert record.inference_sections == {"Inference": "inference-a"}
    assert record.content_location is not None
    assert "/analysis/p1/" in record.content_location

    artifact = Path(record.content_location)
    assert artifact.exists()
    text = artifact.read_text()
    assert "## Source Papers" in text
    assert "## Facts" in text
    assert "## Inference" in text


def test_create_comparison_record_and_artifact(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    _insert_paper(db_conn, "p2", "Paper Two")
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderGood()):
        record = create_comparison(db_conn, sample_config, ["p1", "p2"])

    assert record.analysis_type == "multi_paper_comparison"
    assert record.provider_id == "mock"
    assert record.paper_ids == ["p1", "p2"]
    assert record.prompt_version == "phase8-compare-v1"
    assert record.content_location is not None
    assert "/analysis/multi/" in record.content_location
    assert Path(record.content_location).exists()


def test_list_analyses_filters_by_paper_id(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    _insert_paper(db_conn, "p2", "Paper Two")
    _insert_paper(db_conn, "p3", "Paper Three")
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderGood()):
        create_single_analysis(db_conn, sample_config, "p1")
        create_comparison(db_conn, sample_config, ["p2", "p3"])

    p1_records = list_analyses(db_conn, paper_id="p1")
    assert len(p1_records) == 1
    assert p1_records[0].paper_ids == ["p1"]


def test_get_analysis_returns_none_for_unknown(db_conn: sqlite3.Connection) -> None:
    assert get_analysis(db_conn, "missing-analysis-id") is None


def test_create_comparison_rejects_invalid_paper_count(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    with pytest.raises(ValueError, match="between 2 and 5"):
        create_comparison(db_conn, sample_config, ["p1"])


def test_missing_inference_heading_raises(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    with patch(
        "artimanager.analysis.manager.create_provider",
        return_value=_ProviderMissingHeading(),
    ):
        with pytest.raises(ValueError, match="Facts.*Inference"):
            create_single_analysis(db_conn, sample_config, "p1")


def test_list_analysis_type_filter(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    _insert_paper(db_conn, "p2", "Paper Two")
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderGood()):
        create_single_analysis(db_conn, sample_config, "p1")
        create_comparison(db_conn, sample_config, ["p1", "p2"])

    singles = list_analyses(db_conn, analysis_type="single_paper_summary")
    assert len(singles) == 1
    assert singles[0].analysis_type == "single_paper_summary"


def test_get_analysis_roundtrip(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderGood()):
        created = create_single_analysis(db_conn, sample_config, "p1")

    loaded = get_analysis(db_conn, created.analysis_id)
    assert loaded is not None
    assert loaded.analysis_id == created.analysis_id
    assert loaded.paper_ids == ["p1"]


def test_extra_top_level_heading_after_inference_rejected(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    with patch(
        "artimanager.analysis.manager.create_provider",
        return_value=_ProviderExtraHeadingAfterInference(),
    ):
        with pytest.raises(ValueError, match="exactly two top-level headings"):
            create_single_analysis(db_conn, sample_config, "p1")


def test_partial_analysis_override_is_merged_in_manager(
    db_conn: sqlite3.Connection,
    sample_config: AppConfig,
) -> None:
    _insert_paper(db_conn, "p1", "Paper One")
    sample_config.agent.provider = "mock"
    sample_config.agent.model = "root-model"
    sample_config.agent.api_key_env = "ROOT_KEY"
    sample_config.agent.overrides.analysis = AgentOverrideConfig(model="analysis-model")

    captured: dict[str, str] = {}

    def _fake_create_provider(agent_cfg, **kwargs):
        captured["provider"] = agent_cfg.provider
        captured["model"] = agent_cfg.model
        captured["api_key_env"] = agent_cfg.api_key_env
        return _ProviderGood()

    with patch(
        "artimanager.analysis.manager.create_provider",
        side_effect=_fake_create_provider,
    ):
        create_single_analysis(db_conn, sample_config, "p1")

    assert captured["provider"] == "mock"
    assert captured["model"] == "analysis-model"
    assert captured["api_key_env"] == "ROOT_KEY"
