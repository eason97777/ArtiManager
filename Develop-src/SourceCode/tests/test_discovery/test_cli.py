"""CLI tests for discovery command DeepXiv integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from artimanager.cli.main import cli
from artimanager.db.connection import get_connection, init_db
from artimanager.discovery._models import ExternalPaper


def _write_config(
    tmp_path: Path,
    *,
    db_path: Path,
    notes_root: Path,
    deepxiv_enabled: bool = True,
    token_env: str = "DEEPXIV_TOKEN",
) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'db_path = "{db_path}"\n'
        f'notes_root = "{notes_root}"\n'
        "[deepxiv]\n"
        f"enabled = {'true' if deepxiv_enabled else 'false'}\n"
        f'api_token_env = "{token_env}"\n'
        'base_url = "https://data.rag.ac.cn/arxiv/"\n'
        "timeout_seconds = 20\n"
        'search_mode = "hybrid"\n'
    )
    return cfg


def test_discover_source_deepxiv_happy_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path=db_path, notes_root=notes_root)
    monkeypatch.setenv("DEEPXIV_TOKEN", "token-1")

    papers = [
        ExternalPaper(
            title="DeepXiv Paper",
            authors=["Alice"],
            year=2024,
            abstract="A",
            doi="10.1000/dx",
            arxiv_id="2401.00001",
            source="deepxiv_arxiv",
            external_id="10.1000/dx",
        ),
    ]
    runner = CliRunner()
    with patch("artimanager.discovery.engine.deepxiv_search", return_value=papers):
        res = runner.invoke(
            cli,
            [
                "discover",
                "--config",
                str(cfg),
                "--topic",
                "graph neural networks",
                "--source",
                "deepxiv",
            ],
        )

    assert res.exit_code == 0
    assert "Discovery complete: 1 new, 0 duplicate, 0 error" in res.output
    assert "Source: deepxiv_arxiv" in res.output


def test_discover_source_deepxiv_missing_token_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path=db_path, notes_root=notes_root)
    monkeypatch.delenv("DEEPXIV_TOKEN", raising=False)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "discover",
            "--config",
            str(cfg),
            "--topic",
            "graph neural networks",
            "--source",
            "deepxiv",
        ],
    )
    assert res.exit_code == 1
    assert "Error:" in res.output
    assert "token" in res.output.lower()


def test_discover_source_deepxiv_with_paper_id_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path=db_path, notes_root=notes_root)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "discover",
            "--config",
            str(cfg),
            "--paper-id",
            "p1",
            "--source",
            "deepxiv",
        ],
    )
    assert res.exit_code == 1
    assert "Error:" in res.output
    assert "topic-only runs" in res.output


def test_discovery_inbox_json_includes_provenance(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path=db_path, notes_root=notes_root)
    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id,
         title, authors, status)
        VALUES ('r1', 'topic_anchor', 'graph', 'arxiv', '2401.00001',
                'Graph Paper', '["Alice"]', 'new')
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, source, source_external_id)
        VALUES ('s1', 'v1|test', 'r1', 'topic_anchor', 'graph', 'arxiv', '2401.00001')
        """
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["discovery-inbox", "--config", str(cfg), "--json-output"],
    )

    assert res.exit_code == 0
    assert '"provenance"' in res.output
    assert '"source_external_id": "2401.00001"' in res.output
