"""CLI tests for scanner commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from artimanager.cli.main import cli


def _write_config(tmp_path: Path, papers_dir: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'scan_folders = ["{papers_dir}"]\n'
        f'db_path = "{tmp_path / "test.db"}"\n'
        f'notes_root = "{tmp_path / "notes"}"\n'
        'template_path = "data/paper-note-template.md"\n'
    )
    return cfg


def test_scan_cli_prints_summary_and_details(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    pdf = papers_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    cfg = _write_config(tmp_path, papers_dir)

    result = CliRunner().invoke(
        cli,
        ["scan", "--config", str(cfg)],
    )

    assert result.exit_code == 0
    assert "Scan complete:" in result.output
    assert "1 new, 0 duplicate, 0 failed" in result.output
    assert "[+]" in result.output
    assert str(pdf) in result.output
