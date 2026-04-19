"""Phase 11 paper-detail review and handoff tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from artimanager.db.connection import get_connection
from artimanager.notes.manager import create_note
from artimanager.validation.manager import create_validation
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


def test_paper_detail_shows_discovery_origin_provenance(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute(
        """
        INSERT INTO discovery_results
        (discovery_result_id, trigger_type, trigger_ref, source, external_id,
         title, authors, status, review_action, imported_paper_id)
        VALUES ('r1', 'tracking_rule', 'rule-1', 'semantic_scholar', 'S2-1',
                'Discovery Candidate', '[]', 'imported', 'import', 'p1')
        """
    )
    conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, source, direction, anchor_paper_id, anchor_external_id,
         source_external_id)
        VALUES ('s1', 'v1|s1', 'r1', 'tracking_rule', 'rule-1',
                'semantic_scholar', 'cited_by', 'p1', 'DOI:10.1234/anchor', 'S2-1')
        """
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")

    assert response.status_code == 200
    assert "Discovery Origins" in response.text
    assert "Discovery Candidate" in response.text
    assert "Citation tracking: cited_by for paper p1 using DOI:10.1234/anchor" in response.text


def test_paper_detail_omits_discovery_origins_without_discovery_link(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")

    assert response.status_code == 200
    assert "Discovery Origins" not in response.text


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


def test_paper_detail_renders_citation_tracking_action(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute("UPDATE papers SET doi = '10.1234/example' WHERE paper_id = 'p1'")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")

    assert response.status_code == 200
    assert "Citation Tracking" in response.text
    assert "/papers/p1/tracking-rules" in response.text
    assert "Create citation tracking rule" in response.text


def test_paper_detail_create_cited_by_tracking_rule_for_doi_paper(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute("UPDATE papers SET doi = '10.1234/example' WHERE paper_id = 'p1'")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/tracking-rules",
        data={"direction": "cited_by", "limit": "20"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "Citation+tracking+rule+created" in response.headers["location"]
    conn = get_connection(web_env.db_path)
    rule = conn.execute(
        "SELECT name, rule_type, query, schedule, enabled FROM tracking_rules"
    ).fetchone()
    discovery_count = conn.execute("SELECT COUNT(*) FROM discovery_results").fetchone()[0]
    conn.close()
    payload = json.loads(rule["query"])
    assert rule["name"] == "Citations to Paper One"
    assert rule["rule_type"] == "citation"
    assert rule["schedule"] == "daily"
    assert rule["enabled"] == 1
    assert payload == {
        "schema_version": 1,
        "paper_id": "p1",
        "direction": "cited_by",
        "source": "semantic_scholar",
        "limit": 20,
    }
    assert discovery_count == 0


def test_paper_detail_create_references_tracking_rule_for_arxiv_paper(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute("UPDATE papers SET arxiv_id = '2601.00001' WHERE paper_id = 'p1'")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/tracking-rules",
        data={
            "direction": "references",
            "name": "Custom references",
            "limit": "7",
            "schedule": "weekly",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    conn = get_connection(web_env.db_path)
    rule = conn.execute(
        "SELECT name, rule_type, query, schedule, enabled FROM tracking_rules"
    ).fetchone()
    conn.close()
    payload = json.loads(rule["query"])
    assert rule["name"] == "Custom references"
    assert rule["rule_type"] == "citation"
    assert rule["schedule"] == "weekly"
    assert rule["enabled"] == 1
    assert payload["paper_id"] == "p1"
    assert payload["direction"] == "references"
    assert payload["source"] == "semantic_scholar"
    assert payload["limit"] == 7


def test_paper_detail_tracking_rule_rejects_paper_without_external_id(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/tracking-rules",
        data={"direction": "cited_by", "limit": "20"},
    )

    assert response.status_code == 400
    assert "neither DOI nor arXiv ID" in response.text
    conn = get_connection(web_env.db_path)
    count = conn.execute("SELECT COUNT(*) FROM tracking_rules").fetchone()[0]
    conn.close()
    assert count == 0


def test_paper_detail_tracking_rule_rejects_invalid_direction(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute("UPDATE papers SET doi = '10.1234/example' WHERE paper_id = 'p1'")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/tracking-rules",
        data={"direction": "bad", "limit": "20"},
    )

    assert response.status_code == 400
    assert "direction" in response.text
    conn = get_connection(web_env.db_path)
    count = conn.execute("SELECT COUNT(*) FROM tracking_rules").fetchone()[0]
    conn.close()
    assert count == 0


def test_paper_detail_tracking_rule_rejects_invalid_limit(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.execute("UPDATE papers SET doi = '10.1234/example' WHERE paper_id = 'p1'")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/tracking-rules",
        data={"direction": "cited_by", "limit": "not-a-number"},
    )

    assert response.status_code == 400
    assert "limit must be an integer" in response.text
    conn = get_connection(web_env.db_path)
    count = conn.execute("SELECT COUNT(*) FROM tracking_rules").fetchone()[0]
    conn.close()
    assert count == 0


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


def test_paper_detail_create_note_with_custom_filename(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/notes/create",
        data={"title": "Reading Note", "filename": "reading-note"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    note_path = web_env.notes_root / "reading-note.md"
    assert note_path.exists()
    conn = get_connection(web_env.db_path)
    row = conn.execute("SELECT title, location FROM notes WHERE paper_id = 'p1'").fetchone()
    conn.close()
    assert row["title"] == "Reading Note"
    assert row["location"] == str(note_path)


@pytest.mark.parametrize(
    "filename",
    [
        "/tmp/note.md",
        "nested/note.md",
        "../note.md",
        "notebook.ipynb",
        "",
    ],
)
def test_paper_detail_create_note_rejects_unsafe_filename(
    web_env: WebEnv,
    filename: str,
) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        "/papers/p1/notes/create",
        data={"title": "Reading Note", "filename": filename},
    )

    assert response.status_code == 400
    conn = get_connection(web_env.db_path)
    count = conn.execute("SELECT COUNT(*) FROM notes WHERE paper_id = 'p1'").fetchone()[0]
    conn.close()
    assert count == 0


def test_paper_detail_updates_note_title_and_renames_file(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_note(conn, "p1", web_env.notes_root, title="Old", filename="old.md")
    old_path = Path(record.location)
    old_path.write_text("# Body stays untouched\n", encoding="utf-8")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        f"/papers/p1/notes/{record.note_id}",
        data={"title": "New Title", "filename": "new-name"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    new_path = web_env.notes_root / "new-name.md"
    assert not old_path.exists()
    assert new_path.read_text(encoding="utf-8") == "# Body stays untouched\n"
    conn = get_connection(web_env.db_path)
    row = conn.execute("SELECT title, location FROM notes WHERE note_id = ?", (record.note_id,)).fetchone()
    conn.close()
    assert row["title"] == "New Title"
    assert row["location"] == str(new_path)


def test_paper_detail_note_rename_rejects_overwrite(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_note(conn, "p1", web_env.notes_root, title="Old", filename="old.md")
    target = web_env.notes_root / "taken.md"
    target.write_text("# Existing\n", encoding="utf-8")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        f"/papers/p1/notes/{record.note_id}",
        data={"title": "New Title", "filename": "taken.md"},
    )

    assert response.status_code == 400
    assert "already exists" in response.text
    assert Path(record.location).exists()
    assert target.read_text(encoding="utf-8") == "# Existing\n"


def test_paper_detail_note_rename_rejects_missing_current_file(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_note(conn, "p1", web_env.notes_root, title="Old", filename="old.md")
    Path(record.location).unlink()
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        f"/papers/p1/notes/{record.note_id}",
        data={"title": "New Title", "filename": "new.md"},
    )

    assert response.status_code == 400
    assert "Current Markdown note file does not exist" in response.text


def test_paper_detail_renders_note_copy_and_open_controls(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_routes, "_local_open_supported", lambda: True)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_note(conn, "p1", web_env.notes_root, title="Paper Note")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")

    assert response.status_code == 200
    assert "Markdown Note" in response.text
    assert "Copy path" in response.text
    assert f"/papers/p1/notes/{record.note_id}/open" in response.text
    assert "Update note metadata" in response.text


def test_note_open_route_opens_registered_note_path_only(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    opened_paths: list[Path] = []

    def fake_open(path: Path) -> None:
        opened_paths.append(path)

    monkeypatch.setattr(paper_routes, "_open_local_file", fake_open)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_note(conn, "p1", web_env.notes_root, title="Paper Note")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        f"/papers/p1/notes/{record.note_id}/open",
        data={"path": "/tmp/not-registered.md"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert opened_paths == [Path(record.location)]


def test_note_open_route_rejects_missing_note_id(web_env: WebEnv, monkeypatch) -> None:
    monkeypatch.setattr(paper_routes, "_open_local_file", lambda path: None)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post("/papers/p1/notes/missing/open")

    assert response.status_code == 404


def test_note_open_route_rejects_missing_registered_path(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    opened = False

    def fake_open(path: Path) -> None:
        nonlocal opened
        opened = True

    monkeypatch.setattr(paper_routes, "_open_local_file", fake_open)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_note(conn, "p1", web_env.notes_root, title="Paper Note")
    Path(record.location).unlink()
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(f"/papers/p1/notes/{record.note_id}/open")

    assert response.status_code == 400
    assert "Registered note path does not exist" in response.text
    assert opened is False


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


def test_paper_detail_renders_validation_artifact_controls_and_notebook_label(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_routes, "_local_open_supported", lambda: True)
    notebook_path = web_env.notes_root / "validation.ipynb"
    notebook_path.parent.mkdir(parents=True, exist_ok=True)
    notebook_path.write_text("{}", encoding="utf-8")
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_validation(conn, "p1", path=str(notebook_path))
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/papers/p1")

    assert response.status_code == 200
    assert "Notebook" in response.text
    assert str(notebook_path) in response.text
    assert f"/papers/p1/validations/{record.validation_id}/open" in response.text
    assert "Workspace / Notebook / Artifact Path" in response.text


def test_validation_open_route_opens_registered_path_only(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    opened_paths: list[Path] = []

    def fake_open(path: Path) -> None:
        opened_paths.append(path)

    monkeypatch.setattr(paper_routes, "_open_local_file", fake_open)
    workspace_path = web_env.notes_root / "workspace"
    workspace_path.mkdir(parents=True)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_validation(conn, "p1", path=str(workspace_path))
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(
        f"/papers/p1/validations/{record.validation_id}/open",
        data={"path": "/tmp/not-registered"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert opened_paths == [workspace_path]


def test_validation_open_route_rejects_record_with_no_path(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    opened = False

    def fake_open(path: Path) -> None:
        nonlocal opened
        opened = True

    monkeypatch.setattr(paper_routes, "_open_local_file", fake_open)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_validation(conn, "p1")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(f"/papers/p1/validations/{record.validation_id}/open")

    assert response.status_code == 400
    assert "has no registered path" in response.text
    assert opened is False


def test_validation_open_route_rejects_missing_validation_id(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_routes, "_open_local_file", lambda path: None)
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post("/papers/p1/validations/missing/open")

    assert response.status_code == 404


def test_validation_open_route_rejects_missing_registered_path(
    web_env: WebEnv,
    monkeypatch,
) -> None:
    opened = False

    def fake_open(path: Path) -> None:
        nonlocal opened
        opened = True

    monkeypatch.setattr(paper_routes, "_open_local_file", fake_open)
    missing_path = web_env.notes_root / "missing-workspace"
    conn = get_connection(web_env.db_path)
    _insert_paper(conn, "p1", "Paper One")
    record = create_validation(conn, "p1", path=str(missing_path))
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.post(f"/papers/p1/validations/{record.validation_id}/open")

    assert response.status_code == 400
    assert "Registered validation path does not exist" in response.text
    assert opened is False
