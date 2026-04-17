"""CLI tests for paper update commands."""

from __future__ import annotations

from pathlib import Path

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


def test_paper_update_cli_uses_shared_validation_rules(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO papers (paper_id, title, workflow_status) VALUES ('p1', 'Paper 1', 'inbox')"
    )
    conn.commit()
    conn.close()

    result = CliRunner().invoke(
        cli,
        [
            "paper-update",
            "--config",
            str(cfg),
            "--paper-id",
            "p1",
            "--workflow-status",
            "active",
            "--reading-state",
            "read",
            "--title",
            "Corrected Title",
        ],
    )

    assert result.exit_code == 0
    assert "Paper updated: p1" in result.output
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT workflow_status, reading_state, title FROM papers WHERE paper_id = 'p1'"
    ).fetchone()
    conn.close()
    assert row["workflow_status"] == "active"
    assert row["reading_state"] == "read"
    assert row["title"] == "Corrected Title"


def test_paper_update_cli_rejects_missing_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    result = CliRunner().invoke(
        cli,
        ["paper-update", "--config", str(cfg), "--paper-id", "p1"],
    )

    assert result.exit_code != 0
    assert "no paper fields provided" in result.output
