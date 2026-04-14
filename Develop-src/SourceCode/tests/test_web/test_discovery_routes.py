"""Web discovery route write-action tests."""

from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from artimanager.db.connection import get_connection
from artimanager.web.app import create_app
from tests.test_web.conftest import WebEnv


def _client(env: WebEnv) -> TestClient:
    app = create_app(str(env.config_path))
    return TestClient(app)


def _insert_discovery_result(
    conn: sqlite3.Connection,
    *,
    result_id: str,
    title: str = "Title",
    authors: list[str] | None = None,
    abstract: str | None = None,
    published_at: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    trigger_type: str = "tracking_rule",
    trigger_ref: str | None = "rule-1",
) -> None:
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id,
         title, authors, abstract, published_at, doi, arxiv_id, status)
        VALUES (?, ?, ?, 'arxiv', ?, ?, ?, ?, ?, ?, ?, 'new')
        """,
        (
            result_id,
            trigger_type,
            trigger_ref,
            result_id,
            title,
            json.dumps(authors or []),
            abstract,
            published_at,
            doi,
            arxiv_id,
        ),
    )
    conn.commit()


def test_ignore_action_updates_status(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1")
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/discovery/r1/review",
        data={"action": "ignore", "redirect_to": "/discovery"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    row = conn.execute(
        "SELECT status, review_action FROM discovery_results WHERE discovery_result_id = 'r1'"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("ignored", "ignore")


def test_import_action_creates_paper_and_updates_imported_paper_id(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(
        conn,
        result_id="r1",
        authors=["Alice", "Bob"],
        abstract="Tracking abstract",
        published_at="2025-02-11T00:00:00Z",
        doi="10.1000/example",
        arxiv_id="2502.12345",
    )
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/discovery/r1/review",
        data={"action": "import", "redirect_to": "/discovery"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    imported = conn.execute(
        "SELECT imported_paper_id FROM discovery_results WHERE discovery_result_id = 'r1'"
    ).fetchone()
    assert imported is not None
    paper = conn.execute(
        "SELECT title, year, abstract, doi, arxiv_id, workflow_status FROM papers WHERE paper_id = ?",
        (imported[0],),
    ).fetchone()
    conn.close()
    assert paper is not None
    assert paper[0] == "Title"
    assert paper[1] == 2025
    assert paper[2] == "Tracking abstract"
    assert paper[3] == "10.1000/example"
    assert paper[4] == "2502.12345"
    assert paper[5] == "inbox"


def test_link_to_existing_requires_valid_target_paper(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1")
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/discovery/r1/review",
        data={
            "action": "link_to_existing",
            "link_to_paper": "missing-paper",
            "redirect_to": "/discovery",
        },
    )
    assert response.status_code == 400
    assert "not found" in response.text


def test_follow_author_creates_author_tracking_rule(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", authors=["Alice Smith", "Bob"])
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/discovery/r1/review",
        data={"action": "follow_author", "redirect_to": "/discovery"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    row = conn.execute(
        "SELECT rule_type, query, enabled FROM tracking_rules ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("author", "Alice Smith", 1)


def test_follow_author_is_idempotent_on_repeat(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", authors=["Alice Smith", "Bob"])
    conn.close()

    client = _client(web_env)
    first = client.post(
        "/discovery/r1/review",
        data={"action": "follow_author", "redirect_to": "/discovery"},
        follow_redirects=False,
    )
    assert first.status_code == 303

    second = client.post(
        "/discovery/r1/review",
        data={"action": "follow_author", "redirect_to": "/discovery"},
        follow_redirects=False,
    )
    assert second.status_code == 303
    assert "already+processed+with+follow_author" in second.headers["location"]

    conn = get_connection(web_env.db_path)
    rows = conn.execute(
        "SELECT tracking_rule_id, rule_type, query FROM tracking_rules ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][1] == "author"
    assert rows[0][2] == "Alice Smith"


def test_review_redirect_preserves_filtered_query_string_on_success(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1")
    conn.close()

    client = _client(web_env)
    redirect_to = "/discovery?status=new&trigger_type=tracking_rule&trigger_ref=rule-1&limit=20"
    response = client.post(
        "/discovery/r1/review",
        data={"action": "ignore", "redirect_to": redirect_to},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/discovery?")
    assert "status=new" in location
    assert "trigger_type=tracking_rule" in location
    assert "trigger_ref=rule-1" in location
    assert "limit=20" in location
    assert "ok=" in location


def test_review_validation_failure_preserves_filtered_view_state(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(
        conn,
        result_id="r1",
        title="Tracked Title",
        trigger_type="tracking_rule",
        trigger_ref="rule-1",
    )
    _insert_discovery_result(
        conn,
        result_id="r2",
        title="Topic Title",
        trigger_type="topic_anchor",
        trigger_ref="topic-x",
    )
    conn.close()

    client = _client(web_env)
    redirect_to = "/discovery?status=new&trigger_type=tracking_rule&trigger_ref=rule-1&limit=20"
    response = client.post(
        "/discovery/r1/review",
        data={
            "action": "link_to_existing",
            "link_to_paper": "missing-paper",
            "redirect_to": redirect_to,
        },
    )
    assert response.status_code == 400
    assert "Paper missing-paper not found." in response.text
    assert "Tracked Title" in response.text
    assert "Topic Title" not in response.text
    assert 'name="trigger_ref" value="rule-1"' in response.text
