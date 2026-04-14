"""Tests for database connection and schema initialisation."""

from __future__ import annotations

from pathlib import Path

from artimanager.db.connection import get_connection, init_db


class TestInitDb:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)
        assert db_path.exists()

    def test_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)
        init_db(db_path)  # should not raise

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "dir" / "test.db"
        init_db(db_path)
        assert db_path.exists()


class TestGetConnection:
    def test_returns_connection(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            assert conn is not None
        finally:
            conn.close()

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            result = conn.execute("PRAGMA foreign_keys").fetchone()
            assert result[0] == 1
        finally:
            conn.close()

    def test_wal_mode(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            assert result[0] == "wal"
        finally:
            conn.close()


class TestCoreTables:
    """Verify that core tables exist after init."""

    EXPECTED_TABLES = [
        "papers",
        "file_assets",
        "tags",
        "paper_tags",
        "relationships",
        "zotero_links",
        "notes",
        "validation_records",
        "discovery_results",
        "tracking_rules",
        "analysis_records",
    ]

    def test_all_tables_created(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = {row[0] for row in rows}
            for expected in self.EXPECTED_TABLES:
                assert expected in table_names, f"Missing table: {expected}"
        finally:
            conn.close()


class TestDbUtils:
    """Tests for db.utils module (Phase 5.5 Fix 1)."""

    def test_now_iso_format(self) -> None:
        from artimanager.db.utils import now_iso

        result = now_iso()
        assert result.endswith("Z")
        assert "T" in result
        # Should be valid ISO 8601
        from datetime import datetime
        datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")

    def test_new_id_is_uuid4(self) -> None:
        import uuid
        from artimanager.db.utils import new_id

        result = new_id()
        # Should be a valid UUID string
        uuid.UUID(result, version=4)
