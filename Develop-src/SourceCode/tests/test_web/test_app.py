"""Core web app read-page tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from artimanager.db.connection import get_connection
from artimanager.search.indexer import rebuild_search_index
from artimanager.web.app import create_app
from tests.test_web.conftest import WebEnv


def _client(env: WebEnv) -> TestClient:
    app = create_app(str(env.config_path))
    return TestClient(app)


def test_app_starts_and_dashboard_loads(web_env: WebEnv) -> None:
    client = _client(web_env)
    response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_inbox_page_renders_paper_rows(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        "INSERT INTO papers (paper_id, title, authors, workflow_status) VALUES (?, ?, ?, 'inbox')",
        ("p1", "Inbox Paper", json.dumps(["Alice", "Bob"])),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/inbox")
    assert response.status_code == 200
    assert "Inbox Paper" in response.text
    assert "/papers/p1" in response.text


def test_paper_detail_returns_404_for_missing_paper(web_env: WebEnv) -> None:
    client = _client(web_env)
    response = client.get("/papers/missing-paper-id")
    assert response.status_code == 404


def test_search_page_shows_grouped_results(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        "INSERT INTO papers (paper_id, title, authors, abstract, workflow_status) VALUES (?, ?, ?, ?, 'inbox')",
        ("p-meta", "Graph Methods", json.dumps(["Author A"]), "metadata graph match"),
    )
    conn.execute(
        "INSERT INTO papers (paper_id, title, authors, abstract, workflow_status) VALUES (?, ?, ?, ?, 'inbox')",
        ("p-full", "Unrelated Title", json.dumps(["Author B"]), "no keyword"),
    )
    conn.execute(
        "INSERT INTO file_assets (file_id, paper_id, absolute_path, filename, full_text) VALUES (?, ?, ?, ?, ?)",
        ("f1", "p-full", "/tmp/f1.pdf", "f1.pdf", "graph neural content"),
    )
    rebuild_search_index(conn)
    conn.close()

    client = _client(web_env)
    response = client.get("/search", params={"q": "graph", "source": "all"})
    assert response.status_code == 200
    assert "metadata" in response.text
    assert "fulltext" in response.text


def test_discovery_inbox_filter_works(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id, title, authors, status)
        VALUES ('r1', 'tracking_rule', 'rule-1', 'arxiv', 'x1', 'Tracked Result', ?, 'new')
        """,
        (json.dumps(["A"]),),
    )
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id, title, authors, status)
        VALUES ('r2', 'topic_anchor', 'topic', 'arxiv', 'x2', 'Topic Result', ?, 'new')
        """,
        (json.dumps(["B"]),),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery", params={"trigger_type": "tracking_rule"})
    assert response.status_code == 200
    assert "Tracked Result" in response.text
    assert "Topic Result" not in response.text


def test_tracking_page_renders_created_rules(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'NLP Feed', 'keyword', 'transformer', 'daily', 1)
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/tracking")
    assert response.status_code == 200
    assert "NLP Feed" in response.text
