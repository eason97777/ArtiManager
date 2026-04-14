"""Web tracking route write-action tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from artimanager.db.connection import get_connection
from artimanager.discovery._models import ExternalPaper
from artimanager.tracking.manager import create_tracking_rule
from artimanager.web.app import create_app
from tests.test_web.conftest import WebEnv


class _Provider:
    @property
    def provider_id(self) -> str:
        return "mock"

    def summarize(self, text: str) -> str:
        return f"summary::{text[:18]}"

    def analyze(self, paper: dict, prompt: str) -> str:
        return ""

    def compare(self, papers: list[dict], prompt: str) -> str:
        return ""

    def search_query(self, topic: str) -> list[str]:
        return []


def _client(env: WebEnv) -> TestClient:
    app = create_app(str(env.config_path))
    return TestClient(app)


def test_create_rule_from_form_data(web_env: WebEnv) -> None:
    client = _client(web_env)
    response = client.post(
        "/tracking/create",
        data={
            "name": "NLP Feed",
            "rule_type": "keyword",
            "query": "transformer",
            "schedule": "daily",
            "enabled": "true",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    row = conn.execute(
        "SELECT name, rule_type, query, schedule, enabled FROM tracking_rules"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("NLP Feed", "keyword", "transformer", "daily", 1)


def test_disable_update_rule(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 1)
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/tracking/rule-1/update",
        data={
            "name": "NLP Updated",
            "query": "transformer-xl",
            "schedule": "weekly",
            "enabled": "false",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    row = conn.execute(
        "SELECT name, query, schedule, enabled FROM tracking_rules WHERE tracking_rule_id = 'rule-1'"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("NLP Updated", "transformer-xl", "weekly", 0)


def test_delete_rule(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 1)
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/tracking/rule-1/delete",
        data={"redirect_to": "/tracking"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM tracking_rules WHERE tracking_rule_id = 'rule-1'"
    ).fetchone()
    conn.close()
    assert row[0] == 0


def test_run_all_rules(web_env: WebEnv, monkeypatch) -> None:
    conn = get_connection(web_env.db_path)
    create_tracking_rule(conn, name="NLP", rule_type="keyword", query="graph")
    conn.commit()
    conn.close()

    import artimanager.tracking.runner as runner

    monkeypatch.setattr(runner, "create_provider", lambda cfg, **kwargs: _Provider())
    monkeypatch.setattr(
        runner,
        "arxiv_search",
        lambda query, max_results=20: [
            ExternalPaper(
                title="Graph Tracking Paper",
                authors=["A"],
                year=2025,
                abstract="tracking abstract",
                arxiv_id="2501.12345",
                source="arxiv",
                external_id="2501.12345",
            )
        ],
    )

    client = _client(web_env)
    response = client.post("/tracking/run", data={"limit": "20"}, follow_redirects=False)
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    row = conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()
    conn.close()
    assert row[0] == 1


def test_run_one_disabled_rule_returns_clear_error(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 0)
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post("/tracking/rule-1/run", data={"limit": "20"})
    assert response.status_code == 400
    assert "disabled" in response.text
