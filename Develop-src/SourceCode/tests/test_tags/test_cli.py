"""CLI tests for tag commands and note/tag search filters."""

from __future__ import annotations

import json
import sqlite3
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


def test_tag_add_list_remove(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO papers (paper_id, title, workflow_status) VALUES ('p1', 'Paper 1', 'inbox')")
    conn.commit()
    conn.close()

    runner = CliRunner()
    add_res = runner.invoke(
        cli,
        ["tag-add", "--config", str(cfg), "--paper-id", "p1", "--tag", "Graph ML", "--tag-type", "topic"],
    )
    assert add_res.exit_code == 0
    assert "Tag added: Graph ML" in add_res.output

    list_res = runner.invoke(
        cli,
        ["tag-list", "--config", str(cfg), "--paper-id", "p1", "--json-output"],
    )
    assert list_res.exit_code == 0
    data = json.loads(list_res.output)
    assert len(data) == 1
    assert data[0]["name"] == "Graph ML"

    rm_res = runner.invoke(
        cli,
        ["tag-remove", "--config", str(cfg), "--paper-id", "p1", "--tag", " graph   ml "],
    )
    assert rm_res.exit_code == 0
    assert "Tag removed" in rm_res.output

    list_after = runner.invoke(
        cli,
        ["tag-list", "--config", str(cfg), "--paper-id", "p1"],
    )
    assert list_after.exit_code == 0
    assert "No tags found." in list_after.output


def test_search_source_note(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO papers (paper_id, title, workflow_status) VALUES ('p1', 'Graph Paper', 'inbox')"
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    create_res = runner.invoke(
        cli,
        ["note-create", "--config", str(cfg), "--paper-id", "p1", "--title", "Graph Note"],
    )
    assert create_res.exit_code == 0

    conn = get_connection(db_path)
    row = conn.execute("SELECT location FROM notes WHERE paper_id = 'p1'").fetchone()
    conn.close()
    note_path = Path(row[0])
    note_path.write_text(note_path.read_text() + "\ncustom phrase graphoperator test\n")

    reindex_res = runner.invoke(cli, ["reindex", "--config", str(cfg)])
    assert reindex_res.exit_code == 0

    search_res = runner.invoke(
        cli,
        ["search", "graphoperator", "--config", str(cfg), "--source", "note", "--json-output"],
    )
    assert search_res.exit_code == 0
    data = json.loads(search_res.output)
    assert len(data) == 1
    assert data[0]["paper_id"] == "p1"
    assert data[0]["match_source"] == "note"


def test_note_create_cli_accepts_custom_filename(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO papers (paper_id, title, workflow_status) VALUES ('p1', 'Graph Paper', 'inbox')"
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "note-create",
            "--config",
            str(cfg),
            "--paper-id",
            "p1",
            "--title",
            "Graph Note",
            "--filename",
            "reading-note",
        ],
    )

    assert result.exit_code == 0
    note_path = notes_root / "reading-note.md"
    assert note_path.exists()
    assert f"Path:  {note_path}" in result.output


def test_search_filter_tags(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO papers (paper_id, title, authors, abstract, workflow_status)
           VALUES ('p1', 'Graph Learning', '[]', 'Graph learning details', 'inbox')"""
    )
    conn.execute(
        """INSERT INTO papers (paper_id, title, authors, abstract, workflow_status)
           VALUES ('p2', 'Robot Learning', '[]', 'Robot learning details', 'inbox')"""
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    tag_res = runner.invoke(
        cli,
        ["tag-add", "--config", str(cfg), "--paper-id", "p1", "--tag", "Graph ML"],
    )
    assert tag_res.exit_code == 0

    reindex_res = runner.invoke(cli, ["reindex", "--config", str(cfg)])
    assert reindex_res.exit_code == 0

    search_res = runner.invoke(
        cli,
        [
            "search",
            "learning",
            "--config",
            str(cfg),
            "--source",
            "metadata",
            "--filter-tags",
            " graph   ml ",
            "--json-output",
        ],
    )
    assert search_res.exit_code == 0
    data = json.loads(search_res.output)
    assert len(data) == 1
    assert data[0]["paper_id"] == "p1"
