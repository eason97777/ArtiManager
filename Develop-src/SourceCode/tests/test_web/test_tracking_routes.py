"""Web tracking route write-action tests."""

from __future__ import annotations

import json

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


def test_tracking_page_renders_citation_rule_summary(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'Citations', 'citation', ?, 'daily', 1)
        """,
        (
            json.dumps({
                "schema_version": 1,
                "paper_id": "p1",
                "direction": "references",
                "source": "semantic_scholar",
                "limit": 20,
            }),
        ),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/tracking")

    assert response.status_code == 200
    assert "Citation references for paper p1" in response.text
    assert "source: semantic_scholar" in response.text
    assert "limit: 20" in response.text


def test_tracking_page_renders_openalex_author_rule_summary(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'OpenAlex Alice', 'openalex_author', ?, 'daily', 1)
        """,
        (
            json.dumps({
                "schema_version": 1,
                "author_id": "https://openalex.org/A123456789",
                "display_name": "Alice Smith",
                "source": "openalex",
                "limit": 20,
            }),
        ),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/tracking")

    assert response.status_code == 200
    assert "OpenAlex author watch: Alice Smith / https://openalex.org/A123456789" in response.text
    assert "source: openalex" in response.text
    assert "limit: 20" in response.text


def test_tracking_page_handles_invalid_json_payload(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'Bad Citation', 'citation', 'not-json', 'daily', 1)
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/tracking")

    assert response.status_code == 200
    assert "Invalid payload:" in response.text
    assert "not-json" in response.text


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


def test_delete_rule_preserves_referenced_provenance(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 1)
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id, title)
        VALUES ('r1', 'tracking_rule', 'rule-1', 'arxiv', '2401.00001', 'Candidate')
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, source_external_id)
        VALUES ('s1', 'v1|s1', 'r1', 'tracking_rule', 'rule-1', 'rule-1', 'arxiv', '2401.00001')
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
    rule_count = conn.execute(
        "SELECT COUNT(*) FROM tracking_rules WHERE tracking_rule_id = 'rule-1'"
    ).fetchone()[0]
    provenance = conn.execute(
        "SELECT tracking_rule_id, trigger_ref FROM discovery_result_sources WHERE source_id = 's1'"
    ).fetchone()
    conn.close()
    assert rule_count == 0
    assert tuple(provenance) == (None, "rule-1")


def test_tracking_page_delete_form_exposes_discovery_cleanup_option(
    web_env: WebEnv,
) -> None:
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
    response = client.get("/tracking")

    assert response.status_code == 200
    assert 'name="delete_new_discovery"' in response.text
    assert "Also delete new Discovery candidates produced only by this rule" in response.text


def test_delete_rule_with_cleanup_deletes_eligible_new_discovery(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 1)
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id, title, status)
        VALUES ('r1', 'tracking_rule', 'rule-1', 'arxiv', '2401.00001', 'Eligible Candidate', 'new')
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, source_external_id)
        VALUES ('s1', 'v1|s1', 'r1', 'tracking_rule', 'rule-1', 'rule-1', 'arxiv', '2401.00001')
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/tracking/rule-1/delete",
        data={"redirect_to": "/tracking", "delete_new_discovery": "true"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "deleted+1+new+discovery+candidates" in response.headers["location"]
    conn = get_connection(web_env.db_path)
    result_count = conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    source_count = conn.execute("SELECT COUNT(*) FROM discovery_result_sources").fetchone()[0]
    conn.close()
    assert result_count == 0
    assert source_count == 0

    discovery_response = client.get("/discovery")
    assert "Eligible Candidate" not in discovery_response.text


def test_delete_rule_with_cleanup_preserves_reviewed_and_multisource_candidates(
    web_env: WebEnv,
) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'NLP', 'keyword', 'transformer', 'daily', 1)
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id,
         title, status, review_action)
        VALUES ('r-reviewed', 'tracking_rule', 'rule-1', 'arxiv', '2401.00001',
                'Reviewed Candidate', 'reviewed', 'link_to_existing')
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id, title, status)
        VALUES ('r-multi', 'tracking_rule', 'rule-1', 'arxiv', '2401.00002',
                'Multi Source Candidate', 'new')
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, source_external_id)
        VALUES ('s-reviewed', 'v1|s-reviewed', 'r-reviewed', 'tracking_rule',
                'rule-1', 'rule-1', 'arxiv', '2401.00001')
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, source_external_id)
        VALUES ('s-multi-rule', 'v1|s-multi-rule', 'r-multi', 'tracking_rule',
                'rule-1', 'rule-1', 'arxiv', '2401.00002')
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, source, source_external_id)
        VALUES ('s-multi-topic', 'v1|s-multi-topic', 'r-multi', 'topic_anchor',
                'graph', 'semantic_scholar', 'S2-2')
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/tracking/rule-1/delete",
        data={"redirect_to": "/tracking", "delete_new_discovery": "true"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "deleted+0+new+discovery+candidates" in response.headers["location"]
    conn = get_connection(web_env.db_path)
    result_rows = conn.execute(
        "SELECT discovery_result_id FROM discovery_results ORDER BY discovery_result_id"
    ).fetchall()
    source_rows = conn.execute(
        """
        SELECT source_id, tracking_rule_id, trigger_ref
        FROM discovery_result_sources
        ORDER BY source_id
        """
    ).fetchall()
    conn.close()
    assert [row[0] for row in result_rows] == ["r-multi", "r-reviewed"]
    assert [tuple(row) for row in source_rows] == [
        ("s-multi-rule", None, "rule-1"),
        ("s-multi-topic", None, "graph"),
        ("s-reviewed", None, "rule-1"),
    ]


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


def test_run_all_rules_uses_real_mock_provider_factory(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    conn = get_connection(web_env.db_path)
    create_tracking_rule(conn, name="NLP", rule_type="keyword", query="graph")
    conn.commit()
    conn.close()

    import artimanager.tracking.runner as runner

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
