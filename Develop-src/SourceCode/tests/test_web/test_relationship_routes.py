"""Phase 11 relationship review route tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from artimanager.db.connection import get_connection
from artimanager.web.app import create_app
from tests.test_web.conftest import WebEnv


def _client(env: WebEnv) -> TestClient:
    app = create_app(str(env.config_path))
    return TestClient(app)


def _insert_paper(conn, paper_id: str, title: str) -> None:
    conn.execute(
        "INSERT INTO papers (paper_id, title, authors, workflow_status) VALUES (?, ?, ?, 'inbox')",
        (paper_id, title, json.dumps(["Author A"])),
    )


def _insert_relationship(
    conn,
    *,
    relationship_id: str,
    source_paper_id: str,
    target_paper_id: str,
    status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO relationships
        (relationship_id, source_paper_id, target_paper_id, relationship_type, status,
         evidence_type, evidence_text, confidence, created_by, created_at)
        VALUES (?, ?, ?, 'prior_work', ?, 'agent_inferred', 'reason', 0.71,
                'analysis_pipeline', '2026-01-01T00:00:00Z')
        """,
        (relationship_id, source_paper_id, target_paper_id, status),
    )


def test_relationship_review_queue_filters_by_paper_id_and_status(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Anchor P1")
    _insert_paper(conn, "p2", "Target Suggested")
    _insert_paper(conn, "p3", "Target Confirmed")
    _insert_paper(conn, "p4", "Elsewhere Suggested")
    _insert_relationship(
        conn,
        relationship_id="r1",
        source_paper_id="p1",
        target_paper_id="p2",
        status="suggested",
    )
    _insert_relationship(
        conn,
        relationship_id="r2",
        source_paper_id="p1",
        target_paper_id="p3",
        status="confirmed",
    )
    _insert_relationship(
        conn,
        relationship_id="r3",
        source_paper_id="p2",
        target_paper_id="p4",
        status="suggested",
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/relationships/review", params={"paper_id": "p1", "status": "suggested"})
    assert response.status_code == 200
    assert "Target Suggested" in response.text
    assert "Target Confirmed" not in response.text
    assert "Elsewhere Suggested" not in response.text


def test_confirm_action_updates_status_to_confirmed(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    _insert_paper(conn, "p2", "Paper Two")
    _insert_relationship(
        conn,
        relationship_id="r1",
        source_paper_id="p1",
        target_paper_id="p2",
        status="suggested",
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/relationships/r1/review",
        data={
            "action": "confirm",
            "redirect_to": "/relationships/review?paper_id=p1&status=suggested",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    status = conn.execute(
        "SELECT status FROM relationships WHERE relationship_id = 'r1'"
    ).fetchone()[0]
    conn.close()
    assert status == "confirmed"


def test_reject_action_updates_status_to_rejected(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    _insert_paper(conn, "p2", "Paper Two")
    _insert_relationship(
        conn,
        relationship_id="r1",
        source_paper_id="p1",
        target_paper_id="p2",
        status="suggested",
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/relationships/r1/review",
        data={
            "action": "reject",
            "redirect_to": "/relationships/review?paper_id=p1&status=suggested",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    conn = get_connection(web_env.db_path)
    status = conn.execute(
        "SELECT status FROM relationships WHERE relationship_id = 'r1'"
    ).fetchone()[0]
    conn.close()
    assert status == "rejected"


def test_review_redirect_preserves_queue_filter_state(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    _insert_paper(conn, "p2", "Paper Two")
    _insert_relationship(
        conn,
        relationship_id="r1",
        source_paper_id="p1",
        target_paper_id="p2",
        status="suggested",
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/relationships/r1/review",
        data={
            "action": "confirm",
            "redirect_to": "/relationships/review?paper_id=p1&status=suggested&limit=30",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/relationships/review?")
    assert "paper_id=p1" in location
    assert "status=suggested" in location
    assert "limit=30" in location
    assert "ok=" in location
