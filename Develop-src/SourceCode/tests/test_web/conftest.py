"""Fixtures for web route tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from artimanager.db.connection import init_db


@dataclass
class WebEnv:
    config_path: Path
    db_path: Path
    notes_root: Path


def _write_config(config_path: Path, db_path: Path, notes_root: Path) -> None:
    config_path.write_text(
        f'db_path = "{db_path}"\n'
        f'notes_root = "{notes_root}"\n'
        "tracking_schedule = 'daily'\n"
        "[agent]\n"
        'provider = "mock"\n'
        'model = "mock-model"\n'
    )


@pytest.fixture()
def web_env(tmp_path: Path) -> WebEnv:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    config_path = tmp_path / "config.toml"
    _write_config(config_path, db_path, notes_root)
    return WebEnv(config_path=config_path, db_path=db_path, notes_root=notes_root)
