"""CLI tests for tracking commands and tracking review actions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from artimanager.cli.main import cli
from artimanager.db.connection import get_connection, init_db
from artimanager.discovery._models import ExternalPaper


def _write_config(tmp_path: Path, db_path: Path, notes_root: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'db_path = "{db_path}"\n'
        f'notes_root = "{notes_root}"\n'
        "tracking_schedule = 'daily'\n"
        "[agent]\n"
        'provider = "mock"\n'
        'model = "mock-model"\n'
    )
    return cfg


class _Provider:
    @property
    def provider_id(self) -> str:
        return "mock"

    def summarize(self, text: str) -> str:
        return "summary"

    def analyze(self, paper: dict, prompt: str) -> str:
        return ""

    def compare(self, papers: list[dict], prompt: str) -> str:
        return ""

    def search_query(self, topic: str) -> list[str]:
        return []


def _insert_discovery_result(
    conn: sqlite3.Connection,
    *,
    result_id: str,
    trigger_type: str = "tracking_rule",
    trigger_ref: str | None = "rule-1",
    authors: list[str] | None = None,
    abstract: str | None = None,
    published_at: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO discovery_results "
        "(discovery_result_id, trigger_type, trigger_ref, source, external_id, "
        " title, authors, abstract, published_at, doi, arxiv_id, status) "
        "VALUES (?, ?, ?, 'arxiv', ?, 'Title', ?, ?, ?, ?, ?, 'new')",
        (
            result_id,
            trigger_type,
            trigger_ref,
            result_id,
            json.dumps(authors or []),
            abstract,
            published_at,
            doi,
            arxiv_id,
        ),
    )
    conn.commit()


def test_tracking_create_and_list(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    create_res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "NLP feed",
            "--type", "keyword",
            "--query", "transformer",
        ],
    )
    assert create_res.exit_code == 0
    assert "Tracking rule created:" in create_res.output

    list_res = runner.invoke(
        cli,
        ["tracking-list", "--config", str(cfg), "--json-output"],
    )
    assert list_res.exit_code == 0
    data = json.loads(list_res.output)
    assert len(data) == 1
    assert data[0]["name"] == "NLP feed"


def test_tracking_create_citation_stores_canonical_json(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO papers (paper_id, title, doi, workflow_status) "
        "VALUES ('p1', 'Paper', '10.1234/test', 'inbox')"
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "Citations of Paper",
            "--type", "citation",
            "--paper-id", "p1",
            "--direction", "cited_by",
            "--limit", "20",
        ],
    )

    assert res.exit_code == 0
    conn = get_connection(db_path)
    row = conn.execute("SELECT rule_type, query FROM tracking_rules").fetchone()
    conn.close()
    assert row["rule_type"] == "citation"
    assert json.loads(row["query"]) == {
        "schema_version": 1,
        "paper_id": "p1",
        "direction": "cited_by",
        "source": "semantic_scholar",
        "limit": 20,
    }


def test_tracking_create_non_citation_without_query_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "NLP feed",
            "--type", "keyword",
        ],
    )

    assert res.exit_code == 1
    assert "requires --query" in res.output


def test_tracking_create_citation_rejects_query_plus_anchor_flags(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "Citations",
            "--type", "citation",
            "--query", '{"schema_version":1,"paper_id":"p1","direction":"cited_by","source":"semantic_scholar","limit":20}',
            "--paper-id", "p1",
            "--direction", "cited_by",
        ],
    )

    assert res.exit_code == 1
    assert "either --query JSON or --paper-id/--direction" in res.output


def test_tracking_create_citation_rejects_unknown_paper(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "Citations",
            "--type", "citation",
            "--paper-id", "missing",
            "--direction", "cited_by",
        ],
    )

    assert res.exit_code == 1
    assert "Paper not found" in res.output


def test_tracking_create_citation_accepts_advanced_query_json(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO papers (paper_id, title, arxiv_id, workflow_status) "
        "VALUES ('p1', 'Paper', '2401.00001v2', 'inbox')"
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "References",
            "--type", "citation",
            "--query", '{"schema_version":1,"paper_id":"p1","direction":"references","source":"semantic_scholar","limit":200}',
        ],
    )

    assert res.exit_code == 0
    conn = get_connection(db_path)
    row = conn.execute("SELECT query FROM tracking_rules").fetchone()
    conn.close()
    assert json.loads(row["query"])["limit"] == 100


def test_tracking_create_openalex_author_stores_canonical_json(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "OpenAlex Alice",
            "--type", "openalex_author",
            "--author-id", "A123456789",
            "--display-name", " Alice Smith ",
            "--limit", "250",
        ],
    )

    assert res.exit_code == 0
    conn = get_connection(db_path)
    row = conn.execute("SELECT rule_type, query FROM tracking_rules").fetchone()
    conn.close()
    assert row["rule_type"] == "openalex_author"
    assert json.loads(row["query"]) == {
        "schema_version": 1,
        "author_id": "https://openalex.org/A123456789",
        "display_name": "Alice Smith",
        "source": "openalex",
        "limit": 100,
    }


def test_tracking_create_openalex_author_rejects_query_plus_author_flags(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "OpenAlex Alice",
            "--type", "openalex_author",
            "--query", '{"schema_version":1,"author_id":"A123456789","source":"openalex","limit":20}',
            "--author-id", "A123456789",
        ],
    )

    assert res.exit_code == 1
    assert "either --query JSON or --author-id/--display-name" in res.output


def test_tracking_create_openalex_author_rejects_raw_name(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "OpenAlex Alice",
            "--type", "openalex_author",
            "--author-id", "Alice Smith",
        ],
    )

    assert res.exit_code == 1
    assert "OpenAlex author_id must be a stable ID" in res.output


def test_tracking_create_openalex_author_advanced_query_json(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)

    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "tracking-create",
            "--config", str(cfg),
            "--name", "OpenAlex Alice",
            "--type", "openalex_author",
            "--query", '{"schema_version":1,"author_id":"https://openalex.org/A123456789","display_name":"Alice","source":"openalex","limit":5}',
        ],
    )

    assert res.exit_code == 0
    conn = get_connection(db_path)
    row = conn.execute("SELECT query FROM tracking_rules").fetchone()
    conn.close()
    assert json.loads(row["query"])["author_id"] == "https://openalex.org/A123456789"


def test_tracking_update_disable(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO tracking_rules (tracking_rule_id, name, rule_type, query, schedule, enabled) "
        "VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 1)"
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["tracking-update", "rule-1", "--config", str(cfg), "--disable"],
    )
    assert res.exit_code == 0
    conn = get_connection(db_path)
    row = conn.execute("SELECT enabled FROM tracking_rules WHERE tracking_rule_id = 'rule-1'").fetchone()
    conn.close()
    assert row[0] == 0


def test_tracking_run_stores_inbox_items(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO tracking_rules (tracking_rule_id, name, rule_type, query, schedule, enabled) "
        "VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 1)"
    )
    conn.commit()
    conn.close()

    papers = [ExternalPaper(
        title="P",
        authors=["A"],
        year=2024,
        abstract="Abs",
        arxiv_id="2401.00001",
        source="arxiv",
        external_id="2401.00001",
    )]
    runner = CliRunner()
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=papers):
            res = runner.invoke(
                cli,
                ["tracking-run", "--config", str(cfg)],
            )
    assert res.exit_code == 0
    conn = get_connection(db_path)
    row = conn.execute("SELECT COUNT(*) FROM discovery_results WHERE trigger_type = 'tracking_rule'").fetchone()
    conn.close()
    assert row[0] == 1


def test_discovery_inbox_trigger_type_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    _insert_discovery_result(conn, result_id="r1", trigger_type="tracking_rule", trigger_ref="rule-1")
    _insert_discovery_result(conn, result_id="r2", trigger_type="topic_anchor", trigger_ref="topic")
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["discovery-inbox", "--config", str(cfg), "--trigger-type", "tracking_rule", "--json-output"],
    )
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert len(data) == 1
    assert data[0]["discovery_result_id"] == "r1"


def test_discovery_review_follow_author_creates_rule(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    _insert_discovery_result(conn, result_id="r1", authors=["Alice Smith", "Bob"])
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["discovery-review", "r1", "follow_author", "--config", str(cfg)],
    )
    assert res.exit_code == 0
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT rule_type, query, enabled FROM tracking_rules ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("author", "Alice Smith", 1)


def test_discovery_review_follow_author_is_idempotent_on_repeat(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    _insert_discovery_result(conn, result_id="r1", authors=["Alice Smith", "Bob"])
    conn.close()

    runner = CliRunner()
    first = runner.invoke(
        cli,
        ["discovery-review", "r1", "follow_author", "--config", str(cfg)],
    )
    assert first.exit_code == 0
    assert "followed author 'Alice Smith'" in first.output

    second = runner.invoke(
        cli,
        ["discovery-review", "r1", "follow_author", "--config", str(cfg)],
    )
    assert second.exit_code == 0
    assert "already processed with follow_author" in second.output

    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT tracking_rule_id, rule_type, query FROM tracking_rules ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][1] == "author"
    assert rows[0][2] == "Alice Smith"


def test_discovery_review_mute_topic_disables_rule(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO tracking_rules (tracking_rule_id, name, rule_type, query, schedule, enabled) "
        "VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 1)"
    )
    _insert_discovery_result(conn, result_id="r1", trigger_type="tracking_rule", trigger_ref="rule-1")
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["discovery-review", "r1", "mute_topic", "--config", str(cfg)],
    )
    assert res.exit_code == 0
    conn = get_connection(db_path)
    rule = conn.execute("SELECT enabled FROM tracking_rules WHERE tracking_rule_id = 'rule-1'").fetchone()
    result = conn.execute(
        "SELECT status, review_action FROM discovery_results WHERE discovery_result_id = 'r1'"
    ).fetchone()
    conn.close()
    assert rule[0] == 0
    assert tuple(result) == ("reviewed", "mute_topic")


def test_discovery_review_snooze_marks_saved(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    _insert_discovery_result(conn, result_id="r1")
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["discovery-review", "r1", "snooze", "--config", str(cfg)],
    )
    assert res.exit_code == 0
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT status, review_action FROM discovery_results WHERE discovery_result_id = 'r1'"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("saved", "snooze")


def test_discovery_review_import_tracking_result_maps_fields_correctly(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    _insert_discovery_result(
        conn,
        result_id="r1",
        trigger_type="tracking_rule",
        trigger_ref="rule-1",
        authors=["Alice Smith", "Bob Jones"],
        abstract="A tracking abstract",
        published_at="2024-05-12T00:00:00Z",
        doi="10.1234/example",
        arxiv_id="2405.12345v1",
    )
    conn.close()

    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["discovery-review", "r1", "import", "--config", str(cfg)],
    )
    assert res.exit_code == 0
    assert "imported as paper" in res.output

    conn = get_connection(db_path)
    imported = conn.execute(
        "SELECT imported_paper_id FROM discovery_results WHERE discovery_result_id = 'r1'"
    ).fetchone()
    assert imported is not None
    paper_id = imported[0]
    paper = conn.execute(
        "SELECT title, authors, year, abstract, doi, arxiv_id, workflow_status "
        "FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    conn.close()
    assert paper is not None
    assert paper[0] == "Title"
    assert json.loads(paper[1]) == ["Alice Smith", "Bob Jones"]
    assert paper[2] == 2024
    assert paper[3] == "A tracking abstract"
    assert paper[4] == "10.1234/example"
    assert paper[5] == "2405.12345v1"
    assert paper[6] == "inbox"


def test_discovery_review_import_is_idempotent_for_already_imported_result(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    _insert_discovery_result(
        conn,
        result_id="r1",
        authors=["Alice Smith", "Bob Jones"],
        abstract="A tracking abstract",
        published_at="2024-05-12T00:00:00Z",
        doi="10.1234/example",
        arxiv_id="2405.12345v1",
    )
    conn.close()

    runner = CliRunner()
    first = runner.invoke(
        cli,
        ["discovery-review", "r1", "import", "--config", str(cfg)],
    )
    assert first.exit_code == 0
    assert "imported as paper" in first.output

    conn = get_connection(db_path)
    imported = conn.execute(
        "SELECT imported_paper_id FROM discovery_results WHERE discovery_result_id = 'r1'"
    ).fetchone()
    assert imported is not None
    first_paper_id = imported[0]
    conn.close()

    second = runner.invoke(
        cli,
        ["discovery-review", "r1", "import", "--config", str(cfg)],
    )
    assert second.exit_code == 0
    assert f"already imported as paper {first_paper_id}" in second.output

    conn = get_connection(db_path)
    imported_after = conn.execute(
        "SELECT imported_paper_id FROM discovery_results WHERE discovery_result_id = 'r1'"
    ).fetchone()
    paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    conn.close()
    assert imported_after[0] == first_paper_id
    assert paper_count == 1


def test_tracking_run_rule_id_disabled_rule_returns_error(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    notes_root = tmp_path / "notes"
    init_db(db_path)
    cfg = _write_config(tmp_path, db_path, notes_root)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO tracking_rules (tracking_rule_id, name, rule_type, query, schedule, enabled) "
        "VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 0)"
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    with patch("artimanager.tracking.runner.create_provider", return_value=_Provider()):
        with patch("artimanager.tracking.runner.arxiv_search", return_value=[]):
            res = runner.invoke(
                cli,
                ["tracking-run", "--config", str(cfg), "--rule-id", "rule-1"],
            )
    assert res.exit_code != 0
    assert "disabled" in res.output
