"""Phase 11 paper-detail review and handoff tests."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from artimanager.db.connection import get_connection
from artimanager.web.app import create_app
from artimanager.web.routes import papers as paper_routes
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


def test_paper_detail_renders_file_handoff_controls(web_env: WebEnv, monkeypatch) -> None:
    monkeypatch.setattr(paper_routes, "_local_open_supported", lambda: True)
    pdf_path = web_env.notes_root / "paper.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4")

    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute(
        """
        INSERT INTO file_assets (file_id, paper_id, absolute_path, filename, mime_type, import_status)
        VALUES ('f1', 'p1', ?, 'paper.pdf', 'application/pdf', 'imported')
        """,
        (str(pdf_path),),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")

    assert response.status_code == 200
    assert "paper.pdf" in response.text
    assert str(pdf_path) in response.text
    assert "Copy path" in response.text
    assert "/papers/p1/files/f1/open" in response.text
    assert "Open locally" in response.text


def test_paper_detail_renders_zotero_handoff_controls(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute(
        """
        INSERT INTO zotero_links
        (paper_id, zotero_library_id, zotero_item_key, attachment_mode, last_synced_at)
        VALUES ('p1', '1234567', 'ABCD1234', 'linked', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")

    assert response.status_code == 200
    assert "Library ID" in response.text
    assert "1234567" in response.text
    assert "Library Type" in response.text
    assert "ABCD1234" in response.text
    assert "Copy item key" in response.text


def test_file_open_route_opens_registered_file_only(web_env: WebEnv, monkeypatch) -> None:
    pdf_path = web_env.notes_root / "paper.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4")
    opened_paths: list[Path] = []

    def fake_open(path: Path) -> None:
        opened_paths.append(path)

    monkeypatch.setattr(paper_routes, "_open_local_file", fake_open)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute(
        """
        INSERT INTO file_assets (file_id, paper_id, absolute_path, filename)
        VALUES ('f1', 'p1', ?, 'paper.pdf')
        """,
        (str(pdf_path),),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/files/f1/open",
        data={"absolute_path": "/tmp/not-registered.pdf"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert opened_paths == [pdf_path]


def test_file_open_route_rejects_unknown_file_id(web_env: WebEnv, monkeypatch) -> None:
    monkeypatch.setattr(paper_routes, "_open_local_file", lambda path: None)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post("/papers/p1/files/missing/open")

    assert response.status_code == 404


def test_file_open_route_rejects_missing_registered_path(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    opened = False

    def fake_open(path: Path) -> None:
        nonlocal opened
        opened = True

    monkeypatch.setattr(paper_routes, "_open_local_file", fake_open)
    missing_path = web_env.notes_root / "missing.pdf"
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute(
        """
        INSERT INTO file_assets (file_id, paper_id, absolute_path, filename)
        VALUES ('f1', 'p1', ?, 'missing.pdf')
        """,
        (str(missing_path),),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post("/papers/p1/files/f1/open")

    assert response.status_code == 400
    assert "Registered file path does not exist" in response.text
    assert opened is False


def test_open_local_file_uses_argument_list_without_shell(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append((command, kwargs))
        return None

    monkeypatch.setattr(paper_routes.sys, "platform", "darwin")
    monkeypatch.setattr(paper_routes.subprocess, "run", fake_run)

    paper_routes._open_local_file(pdf_path)

    assert calls == [(["open", str(pdf_path)], {"check": False, "timeout": 5})]
    assert calls[0][1].get("shell") is not True


def test_paper_state_update_persists_and_updates_detail_page(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/state",
        data={
            "workflow_status": "active",
            "reading_state": "read",
            "research_state": "relevant",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "active" in response.text
    assert "read" in response.text
    assert "relevant" in response.text
    conn = get_connection(web_env.db_path)
    row = conn.execute(
        "SELECT workflow_status, reading_state, research_state FROM papers WHERE paper_id = 'p1'"
    ).fetchone()
    conn.close()
    assert row["workflow_status"] == "active"
    assert row["reading_state"] == "read"
    assert row["research_state"] == "relevant"


def test_paper_state_update_rejects_invalid_value(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/state",
        data={"workflow_status": "not-a-state"},
    )

    assert response.status_code == 400
    assert "Invalid workflow_status" in response.text


def test_paper_detail_tag_add_and_remove(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    add_response = client.post(
        "/papers/p1/tags",
        data={"tag_name": " Graph   ML ", "tag_type": "topic"},
        follow_redirects=True,
    )
    assert add_response.status_code == 200
    assert "Graph ML" in add_response.text

    conn = get_connection(web_env.db_path)
    tag_row = conn.execute("SELECT name, tag_type FROM tags").fetchone()
    conn.close()
    assert tag_row["name"] == "Graph ML"
    assert tag_row["tag_type"] == "topic"

    remove_response = client.post(
        "/papers/p1/tags/remove",
        data={"tag_name": "graph ml"},
        follow_redirects=True,
    )
    assert remove_response.status_code == 200
    assert "No tags attached." in remove_response.text


def test_paper_detail_tag_remove_rejects_empty_tag(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/tags/remove",
        data={"tag_name": "   "},
    )

    assert response.status_code == 400
    assert "Tag name cannot be empty" in response.text


def test_paper_detail_tag_remove_rejects_missing_paper(web_env: WebEnv) -> None:
    client = _client(web_env)
    response = client.post(
        "/papers/missing/tags/remove",
        data={"tag_name": "Graph ML"},
    )

    assert response.status_code == 404


def test_paper_detail_create_note_is_idempotent(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    first = client.post("/papers/p1/notes/create", follow_redirects=True)
    second = client.post("/papers/p1/notes/create", follow_redirects=True)

    assert first.status_code == 200
    assert second.status_code == 200
    conn = get_connection(web_env.db_path)
    count = conn.execute("SELECT COUNT(*) FROM notes WHERE paper_id = 'p1'").fetchone()[0]
    location = conn.execute("SELECT location FROM notes WHERE paper_id = 'p1'").fetchone()[0]
    conn.close()
    assert count == 1
    assert Path(location).exists()


def test_paper_metadata_correction_updates_allowed_fields(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Bad Title")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/metadata",
        data={
            "title": "Corrected Title",
            "authors": "Alice; Bob",
            "year": "2026",
            "doi": "10.1234/example",
            "arxiv_id": "2601.00001",
            "abstract": "Corrected abstract",
            "unknown": "ignored",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Corrected Title" in response.text
    conn = get_connection(web_env.db_path)
    row = conn.execute(
        "SELECT title, authors, year, doi, arxiv_id, abstract FROM papers WHERE paper_id = 'p1'"
    ).fetchone()
    conn.close()
    assert row["title"] == "Corrected Title"
    assert json.loads(row["authors"]) == ["Alice", "Bob"]
    assert row["year"] == 2026
    assert row["doi"] == "10.1234/example"
    assert row["arxiv_id"] == "2601.00001"
    assert row["abstract"] == "Corrected abstract"


def test_paper_metadata_correction_rejects_unknown_paper(web_env: WebEnv) -> None:
    client = _client(web_env)
    response = client.post(
        "/papers/missing/metadata",
        data={"title": "Corrected Title"},
    )

    assert response.status_code == 404


def test_paper_detail_validation_form_creates_metadata_record(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/validations",
        data={
            "path": "/tmp/repro",
            "repo_url": "https://example.com/repo.git",
            "environment_note": "Python 3.12",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "/tmp/repro" in response.text
    conn = get_connection(web_env.db_path)
    row = conn.execute(
        "SELECT path, repo_url, environment_note, outcome FROM validation_records WHERE paper_id = 'p1'"
    ).fetchone()
    conn.close()
    assert row["path"] == "/tmp/repro"
    assert row["repo_url"] == "https://example.com/repo.git"
    assert row["environment_note"] == "Python 3.12"
    assert row["outcome"] == "not_attempted"
