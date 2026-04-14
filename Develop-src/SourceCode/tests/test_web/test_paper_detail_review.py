"""Phase 11 paper-detail review and handoff tests."""

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


def test_paper_detail_shows_note_path_and_preview_when_file_exists(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    note_path = web_env.notes_root / "p1.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# Note\nThis is a preview line for paper detail.")
    conn.execute(
        """
        INSERT INTO notes
        (note_id, paper_id, note_type, location, title, created_at, updated_at, template_version)
        VALUES ('n1', 'p1', 'markdown_note', ?, 'Paper Note', '2026-01-01T00:00:00Z',
                '2026-01-01T00:00:00Z', 'v2')
        """,
        (str(note_path),),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")
    assert response.status_code == 200
    assert str(note_path) in response.text
    assert "This is a preview line for paper detail." in response.text


def test_paper_detail_shows_missing_note_file_warning(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    missing_path = web_env.notes_root / "missing-note.md"
    conn.execute(
        """
        INSERT INTO notes
        (note_id, paper_id, note_type, location, title, created_at, updated_at, template_version)
        VALUES ('n1', 'p1', 'markdown_note', ?, 'Missing Note', '2026-01-01T00:00:00Z',
                '2026-01-01T00:00:00Z', 'v2')
        """,
        (str(missing_path),),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")
    assert response.status_code == 200
    assert "missing file reference" in response.text


def test_paper_detail_shows_validation_paths_and_repo_urls(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute(
        """
        INSERT INTO validation_records
        (validation_id, paper_id, path, repo_url, environment_note, outcome, summary, updated_at)
        VALUES ('v1', 'p1', '/tmp/validation/run1', 'https://example.com/repo.git',
                'py312', 'in_progress', 'working through setup', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")
    assert response.status_code == 200
    assert "/tmp/validation/run1" in response.text
    assert "https://example.com/repo.git" in response.text


def test_paper_detail_shows_analysis_artifact_links(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    artifact_path = str((web_env.notes_root / "analysis" / "p1" / "a1.md"))
    conn.execute(
        """
        INSERT INTO analysis_records
        (analysis_id, analysis_type, paper_ids, prompt_version, provider_id, evidence_scope,
         content_location, fact_sections, inference_sections, created_at)
        VALUES ('a1', 'single_paper_summary', ?, 'phase8-analysis-v1', 'mock', 'single_paper',
                ?, '{"Facts":"x"}', '{"Inference":"y"}', '2026-01-01T00:00:00Z')
        """,
        (json.dumps(["p1"]), artifact_path),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")
    assert response.status_code == 200
    assert "/analyses/a1" in response.text
    assert artifact_path in response.text


def test_paper_detail_renders_relationship_review_controls_for_suggested(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    _insert_paper(conn, "p2", "Paper Two")
    conn.execute(
        """
        INSERT INTO relationships
        (relationship_id, source_paper_id, target_paper_id, relationship_type, status,
         evidence_type, evidence_text, confidence, created_by, created_at)
        VALUES ('r1', 'p1', 'p2', 'prior_work', 'suggested',
                'agent_inferred', 'reason', 0.82, 'analysis_pipeline', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")
    assert response.status_code == 200
    assert "/relationships/r1/review" in response.text
    assert 'name="action" value="confirm"' in response.text
    assert 'name="action" value="reject"' in response.text
