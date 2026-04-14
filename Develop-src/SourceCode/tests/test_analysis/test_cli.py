"""CLI tests for Phase 8 analysis commands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from artimanager.cli.main import cli
from artimanager.db.connection import get_connection, init_db


def _write_config(tmp_path: Path, db_path: Path, notes_root: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'db_path = "{db_path}"\n'
        f'notes_root = "{notes_root}"\n'
        "[agent]\n"
        'provider = "mock"\n'
        'model = "mock-model"\n'
    )
    return cfg


def _insert_paper(
    conn: sqlite3.Connection,
    paper_id: str,
    title: str,
) -> None:
    conn.execute(
        "INSERT INTO papers (paper_id, title, authors, abstract, workflow_status) "
        "VALUES (?, ?, ?, ?, 'inbox')",
        (paper_id, title, json.dumps(["A"]), "Abstract"),
    )
    conn.commit()


class _ProviderAnalysis:
    @property
    def provider_id(self) -> str:
        return "mock"

    def analyze(self, paper: dict, prompt: str) -> str:
        return "## Facts\nfact\n\n## Inference\ninference"

    def compare(self, papers: list[dict], prompt: str) -> str:
        return "## Facts\nfact-compare\n\n## Inference\ninference-compare"

    def search_query(self, topic: str) -> list[str]:
        return []

    def summarize(self, text: str) -> str:
        return text


class _ProviderSuggest:
    @property
    def provider_id(self) -> str:
        return "mock"

    def analyze(self, paper: dict, prompt: str) -> str:
        return ""

    def compare(self, papers: list[dict], prompt: str) -> str:
        if "follow_up_work" in prompt:
            return "p2\t0.72\tfollow up reason"
        return "p2\t0.81\trelated reason"

    def search_query(self, topic: str) -> list[str]:
        return []

    def summarize(self, text: str) -> str:
        return text


class _ProviderFailure:
    @property
    def provider_id(self) -> str:
        return "mock"

    def analyze(self, paper: dict, prompt: str) -> str:
        raise RuntimeError("provider failed")

    def compare(self, papers: list[dict], prompt: str) -> str:
        raise RuntimeError("provider failed")

    def search_query(self, topic: str) -> list[str]:
        return []

    def summarize(self, text: str) -> str:
        return text


class _ProviderNotImplemented:
    @property
    def provider_id(self) -> str:
        return "mock"

    def analyze(self, paper: dict, prompt: str) -> str:
        raise NotImplementedError("provider not implemented")

    def compare(self, papers: list[dict], prompt: str) -> str:
        raise NotImplementedError("provider not implemented")

    def search_query(self, topic: str) -> list[str]:
        return []

    def summarize(self, text: str) -> str:
        return text


def test_analysis_create_writes_record_and_artifact(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    conn = get_connection(db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.close()
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderAnalysis()):
        result = runner.invoke(
            cli,
            ["analysis-create", "--config", str(cfg), "--paper-id", "p1"],
        )

    assert result.exit_code == 0
    assert "Analysis created:" in result.output
    conn = get_connection(db_path)
    row = conn.execute("SELECT analysis_id, content_location FROM analysis_records").fetchone()
    conn.close()
    assert row is not None
    assert Path(row[1]).exists()


def test_analysis_compare_rejects_too_few_papers(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analysis-compare", "--config", str(cfg), "--paper-id", "p1"],
    )
    assert result.exit_code != 0
    assert "between 2 and 5" in result.output


def test_analysis_list_filters_by_paper_id(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    conn = get_connection(db_path)
    _insert_paper(conn, "p1", "Paper One")
    _insert_paper(conn, "p2", "Paper Two")
    _insert_paper(conn, "p3", "Paper Three")
    conn.close()
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderAnalysis()):
        runner.invoke(cli, ["analysis-create", "--config", str(cfg), "--paper-id", "p1"])
        runner.invoke(
            cli,
            ["analysis-compare", "--config", str(cfg), "--paper-id", "p2", "--paper-id", "p3"],
        )

    result = runner.invoke(
        cli,
        ["analysis-list", "--config", str(cfg), "--paper-id", "p1", "--json-output"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["paper_ids"] == ["p1"]


def test_analysis_show_not_found(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analysis-show", "missing", "--config", str(cfg)],
    )
    assert result.exit_code != 0
    assert "not found" in result.output


def test_analysis_suggest_related_creates_reviewable_suggestions(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    conn = get_connection(db_path)
    _insert_paper(conn, "p1", "Anchor")
    _insert_paper(conn, "p2", "Candidate")
    conn.close()
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    with patch("artimanager.analysis.suggest.create_provider", return_value=_ProviderSuggest()):
        result = runner.invoke(
            cli,
            [
                "analysis-suggest",
                "--config",
                str(cfg),
                "--paper-id",
                "p1",
                "--mode",
                "related",
                "--candidate-paper-id",
                "p2",
            ],
        )

    assert result.exit_code == 0
    assert "Relationships created: 1" in result.output
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT relationship_type, status, evidence_type, created_by "
        "FROM relationships WHERE source_paper_id = 'p1' AND target_paper_id = 'p2'"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("prior_work", "suggested", "agent_inferred", "analysis_pipeline")


def test_analysis_suggest_follow_up_creates_reviewable_suggestions(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    conn = get_connection(db_path)
    _insert_paper(conn, "p1", "Anchor")
    _insert_paper(conn, "p2", "Candidate")
    conn.close()
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    with patch("artimanager.analysis.suggest.create_provider", return_value=_ProviderSuggest()):
        result = runner.invoke(
            cli,
            [
                "analysis-suggest",
                "--config",
                str(cfg),
                "--paper-id",
                "p1",
                "--mode",
                "follow_up",
                "--candidate-paper-id",
                "p2",
            ],
        )

    assert result.exit_code == 0
    assert "Relationships created: 1" in result.output
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT relationship_type, status, evidence_type, created_by "
        "FROM relationships WHERE source_paper_id = 'p1' AND target_paper_id = 'p2'"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("follow_up_work", "suggested", "agent_inferred", "analysis_pipeline")


def test_analysis_create_provider_failure_is_clean_cli_error(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    conn = get_connection(db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.close()
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderNotImplemented()):
        result = runner.invoke(
            cli,
            ["analysis-create", "--config", str(cfg), "--paper-id", "p1"],
        )

    assert result.exit_code != 0
    assert "Error: provider not implemented" in result.output
    conn = get_connection(db_path)
    row = conn.execute("SELECT COUNT(*) FROM analysis_records").fetchone()
    conn.close()
    assert row[0] == 0


def test_analysis_compare_provider_failure_is_clean_cli_error(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    conn = get_connection(db_path)
    _insert_paper(conn, "p1", "Paper One")
    _insert_paper(conn, "p2", "Paper Two")
    conn.close()
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    with patch("artimanager.analysis.manager.create_provider", return_value=_ProviderFailure()):
        result = runner.invoke(
            cli,
            [
                "analysis-compare",
                "--config",
                str(cfg),
                "--paper-id",
                "p1",
                "--paper-id",
                "p2",
            ],
        )

    assert result.exit_code != 0
    assert "Error: provider failed" in result.output
    conn = get_connection(db_path)
    row = conn.execute("SELECT COUNT(*) FROM analysis_records").fetchone()
    conn.close()
    assert row[0] == 0


def test_analysis_suggest_provider_failure_is_clean_cli_error_and_rollback(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    conn = get_connection(db_path)
    _insert_paper(conn, "p1", "Anchor")
    _insert_paper(conn, "p2", "Candidate")
    conn.close()
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    with patch("artimanager.analysis.suggest.create_provider", return_value=_ProviderFailure()):
        result = runner.invoke(
            cli,
            [
                "analysis-suggest",
                "--config",
                str(cfg),
                "--paper-id",
                "p1",
                "--mode",
                "related",
                "--candidate-paper-id",
                "p2",
            ],
        )

    assert result.exit_code != 0
    assert "Error: provider failed" in result.output
    conn = get_connection(db_path)
    analysis_count = conn.execute("SELECT COUNT(*) FROM analysis_records").fetchone()[0]
    rel_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    conn.close()
    assert analysis_count == 0
    assert rel_count == 0
