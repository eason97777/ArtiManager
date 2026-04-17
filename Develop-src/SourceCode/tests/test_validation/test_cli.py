"""CLI tests for validation commands."""

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


def test_validation_create_persists_after_command_exit(tmp_path: Path) -> None:
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

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "validation-create",
            "--config",
            str(cfg),
            "--paper-id",
            "p1",
            "--path",
            "/tmp/validation-workspace",
            "--repo-url",
            "https://example.com/repo.git",
            "--env-note",
            "Python 3.12",
        ],
    )

    assert result.exit_code == 0
    assert "Validation created:" in result.output

    reopened = get_connection(db_path)
    try:
        row = reopened.execute(
            """
            SELECT paper_id, path, repo_url, environment_note, outcome
            FROM validation_records
            WHERE paper_id = 'p1'
            """
        ).fetchone()
    finally:
        reopened.close()

    assert row is not None
    assert row["paper_id"] == "p1"
    assert row["path"] == "/tmp/validation-workspace"
    assert row["repo_url"] == "https://example.com/repo.git"
    assert row["environment_note"] == "Python 3.12"
    assert row["outcome"] == "not_attempted"
