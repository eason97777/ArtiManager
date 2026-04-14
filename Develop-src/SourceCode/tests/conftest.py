"""Shared pytest fixtures for ArtiManager tests."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from artimanager.config import AppConfig
from artimanager.db.connection import get_connection, init_db


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test artifacts."""
    return tmp_path


@pytest.fixture()
def sample_config(tmp_path: Path) -> AppConfig:
    """Provide a minimal AppConfig pointing to temp paths."""
    return AppConfig(
        scan_folders=[str(tmp_path / "papers")],
        db_path=str(tmp_path / "test.db"),
        notes_root=str(tmp_path / "notes"),
    )


@pytest.fixture()
def db_conn(sample_config: AppConfig) -> Generator[sqlite3.Connection, None, None]:
    """Provide an initialised in-memory-like temp database connection."""
    init_db(sample_config.db_path)
    conn = get_connection(sample_config.db_path)
    yield conn
    conn.close()
