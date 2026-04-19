"""Web discovery route write-action tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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


def _insert_provenance(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    result_id: str,
    source: str = "arxiv",
    trigger_type: str = "tracking_rule",
    trigger_ref: str | None = "rule-1",
    tracking_rule_id: str | None = None,
    direction: str | None = None,
    anchor_paper_id: str | None = None,
    anchor_external_id: str | None = None,
    anchor_author_id: str | None = None,
    source_external_id: str | None = None,
    relevance_score: float | None = None,
    relevance_context: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO discovery_result_sources
        (source_id, provenance_key, discovery_result_id, trigger_type,
         trigger_ref, tracking_rule_id, source, direction, anchor_paper_id,
         anchor_external_id, anchor_author_id, source_external_id,
         relevance_score, relevance_context)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            f"v1|{source_id}",
            result_id,
            trigger_type,
            trigger_ref,
            tracking_rule_id,
            source,
            direction,
            anchor_paper_id,
            anchor_external_id,
            anchor_author_id,
            source_external_id,
            relevance_score,
            relevance_context,
        ),
    )
    conn.commit()


def test_discovery_inbox_renders_single_provenance_row(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="Tracked Title")
    _insert_provenance(
        conn,
        source_id="s1",
        result_id="r1",
        source="semantic_scholar",
        trigger_type="topic_anchor",
        trigger_ref="graph",
        source_external_id="S2-1",
    )
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Why shown" in response.text
    assert "Topic discovery via semantic_scholar" in response.text
    assert "source external: S2-1" in response.text
    assert 'class="provenance-heading"' in response.text
    assert 'class="discovery-context-row"' in response.text
    assert "rule id: graph" not in response.text
    assert "trigger ref: graph" in response.text


def test_discovery_inbox_renders_multiple_provenance_rows(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute("INSERT INTO papers (paper_id, title, workflow_status) VALUES ('p1', 'Anchor', 'inbox')")
    _insert_discovery_result(conn, result_id="r1", title="Multi Trigger")
    _insert_provenance(
        conn,
        source_id="s1",
        result_id="r1",
        source="semantic_scholar",
        trigger_type="topic_anchor",
        trigger_ref="graph",
    )
    _insert_provenance(
        conn,
        source_id="s2",
        result_id="r1",
        source="arxiv",
        trigger_type="paper_anchor",
        trigger_ref="p1",
        anchor_paper_id="p1",
    )
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Topic discovery via semantic_scholar" in response.text
    assert "Paper-anchored discovery from paper p1" in response.text
    assert "rule id: p1" not in response.text
    assert "trigger ref: p1" in response.text


def test_discovery_inbox_handles_missing_provenance(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="Legacy Result")
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Legacy Result" in response.text
    assert "No provenance recorded." in response.text


def test_discovery_inbox_compact_author_line_for_no_authors(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="No Authors", authors=[])
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "(unknown)" in response.text
    assert 'class="muted author-line"' in response.text


def test_discovery_inbox_compact_author_line_for_small_author_list(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(
        conn,
        result_id="r1",
        title="Three Authors",
        authors=["Alice Smith", "Bob Lee", "Carol Wang"],
    )
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Alice Smith, Bob Lee, Carol Wang" in response.text
    assert "+1 more" not in response.text


def test_discovery_inbox_compact_author_line_for_long_author_list(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(
        conn,
        result_id="r1",
        title="Many Authors",
        authors=["Alice Smith", "Bob Lee", "Carol Wang", "Dan Wu", "Eve Kim"],
    )
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Alice Smith, Bob Lee, Carol Wang, +2 more" in response.text
    assert 'title="Alice Smith, Bob Lee, Carol Wang, Dan Wu, Eve Kim"' in response.text


def test_discovery_inbox_sanitizes_legacy_bad_summary(web_env: WebEnv) -> None:
    bad_summary = (
        "Summary: I'd be happy to summarize that, but I don't see any text provided "
        "beyond your description of the topic. Could you paste the full text you'd like me to summarize?"
    )
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="Legacy Bad Summary")
    conn.execute(
        "UPDATE discovery_results SET relevance_context = ? WHERE discovery_result_id = 'r1'",
        (bad_summary,),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Summary unavailable: provider did not return a usable summary" in response.text
    assert "Could you paste the full text" not in response.text


def test_discovery_inbox_hides_legacy_zero_score_local_matches(web_env: WebEnv) -> None:
    context = (
        "Summary: Useful summary\n"
        "Tracking rule: k (keyword:graph)\n"
        "Local matches:\n"
        "- p1: Unrelated Graph Paper"
    )
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="Legacy Local Matches")
    conn.execute(
        """
        UPDATE discovery_results
        SET relevance_score = 0.0, relevance_context = ?
        WHERE discovery_result_id = 'r1'
        """,
        (context,),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Local title-overlap matches:" in response.text
    assert "Unrelated Graph Paper" not in response.text
    assert "- (none)" in response.text


def test_discovery_inbox_keeps_positive_score_legacy_local_matches(web_env: WebEnv) -> None:
    context = (
        "Summary: Useful summary\n"
        "Tracking rule: k (keyword:graph)\n"
        "Local matches:\n"
        "- p1: Related Graph Paper"
    )
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="Legacy Local Matches")
    conn.execute(
        """
        UPDATE discovery_results
        SET relevance_score = 0.5, relevance_context = ?
        WHERE discovery_result_id = 'r1'
        """,
        (context,),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Local title-overlap matches:" in response.text
    assert "Related Graph Paper" in response.text


def test_discovery_inbox_uses_relevance_wrapping_classes(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="Long Context")
    conn.execute(
        "UPDATE discovery_results SET relevance_context = ? WHERE discovery_result_id = 'r1'",
        ("Summary: " + "x" * 240,),
    )
    conn.commit()
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert 'class="table discovery-table"' in response.text
    assert 'class="discovery-context-cell"' in response.text
    assert 'class="relevance"' in response.text


def test_discovery_css_wraps_relevance_context() -> None:
    css = Path("src/artimanager/web/static/app.css").read_text()
    assert ".relevance pre" in css
    assert "white-space: pre-wrap" in css
    assert "overflow-wrap: anywhere" in css
    assert ".provenance-heading" in css
    assert ".discovery-context-row" in css


def test_discovery_inbox_renders_citation_provenance(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute("INSERT INTO papers (paper_id, title, workflow_status) VALUES ('p1', 'Anchor', 'inbox')")
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'Citations', 'citation',
                '{"schema_version":1,"paper_id":"p1","direction":"cited_by","source":"semantic_scholar","limit":20}',
                'daily', 1)
        """
    )
    _insert_discovery_result(conn, result_id="r1", title="Citing Paper")
    _insert_provenance(
        conn,
        source_id="s1",
        result_id="r1",
        source="semantic_scholar",
        tracking_rule_id="rule-1",
        direction="cited_by",
        anchor_paper_id="p1",
        anchor_external_id="DOI:10.1234/example",
        source_external_id="S2-1",
    )
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Citation tracking: cited_by for paper p1 using DOI:10.1234/example" in response.text
    assert "rule: Citations (citation)" in response.text


def test_discovery_inbox_renders_openalex_provenance(web_env: WebEnv) -> None:
    conn = get_connection(web_env.db_path)
    conn.execute(
        """
        INSERT INTO tracking_rules
        (tracking_rule_id, name, rule_type, query, schedule, enabled)
        VALUES ('rule-1', 'OpenAlex Alice', 'openalex_author',
                '{"schema_version":1,"author_id":"https://openalex.org/A123456789","display_name":"Alice Smith","source":"openalex","limit":20}',
                'daily', 1)
        """
    )
    _insert_discovery_result(conn, result_id="r1", title="OpenAlex Work")
    _insert_provenance(
        conn,
        source_id="s1",
        result_id="r1",
        source="openalex",
        tracking_rule_id="rule-1",
        direction="openalex_author_work",
        anchor_author_id="https://openalex.org/A123456789",
        source_external_id="https://openalex.org/W123",
    )
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "OpenAlex author watch: Alice Smith / https://openalex.org/A123456789" in response.text
    assert "source external: https://openalex.org/W123" in response.text


def test_discovery_inbox_deleted_rule_provenance_uses_trigger_ref_fallback(
    web_env: WebEnv,
) -> None:
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="Deleted Rule Candidate")
    _insert_provenance(
        conn,
        source_id="s1",
        result_id="r1",
        tracking_rule_id=None,
        trigger_ref="rule-deleted",
        source="arxiv",
        source_external_id="2401.00001",
    )
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Tracking rule rule-deleted found this candidate" in response.text
    assert "rule id: rule-deleted" in response.text


def test_discovery_inbox_sanitizes_legacy_provenance_context(
    web_env: WebEnv,
) -> None:
    context = (
        "Summary: Could you paste the full text you'd like me to summarize?\n"
        "Tracking rule: k (keyword:graph)\n"
        "Local matches:\n"
        "- p1: Unrelated Graph Paper"
    )
    conn = get_connection(web_env.db_path)
    _insert_discovery_result(conn, result_id="r1", title="Legacy Provenance Context")
    _insert_provenance(
        conn,
        source_id="s1",
        result_id="r1",
        source="arxiv",
        source_external_id="2401.00001",
        relevance_score=0.0,
        relevance_context=context,
    )
    conn.close()

    client = _client(web_env)
    response = client.get("/discovery")

    assert response.status_code == 200
    assert "Summary unavailable: provider did not return a usable summary" in response.text
    assert "Could you paste the full text" not in response.text
    assert "Unrelated Graph Paper" not in response.text


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
    _insert_discovery_result(
        conn,
        result_id="r1",
        authors=["Alice Smith", "Bob", "Carol Wang", "Dan Wu"],
    )
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
