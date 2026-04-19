"""ArtiManager CLI — primary interface for early phases."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import click

from artimanager.analysis.manager import (
    create_comparison,
    create_single_analysis,
    get_analysis,
    list_analyses,
)
from artimanager.analysis.suggest import (
    suggest_follow_up_work,
    suggest_related_work,
)
from artimanager.config import load_config
from artimanager.db.connection import get_connection, init_db
from artimanager.discovery.engine import run_discovery
from artimanager.discovery.provenance import list_discovery_sources
from artimanager.discovery.review import review_discovery_result
from artimanager.notes.manager import create_note, get_note, init_note_from_template
from artimanager.papers.manager import (
    READING_STATE_VALUES,
    RESEARCH_STATE_VALUES,
    WORKFLOW_STATUS_VALUES,
    update_paper_metadata,
    update_paper_state,
)
from artimanager.scanner.intake import run_intake
from artimanager.search.indexer import index_paper, rebuild_search_index
from artimanager.search.query import SearchFilters, search_all, search_fulltext, search_notes, search_papers
from artimanager.tags.manager import add_tag_to_paper, list_tags_for_paper, remove_tag_from_paper
from artimanager.tracking.manager import (
    create_tracking_rule,
    delete_tracking_rule,
    list_tracking_rules,
    serialize_openalex_author_tracking_query,
    serialize_citation_tracking_query,
    update_tracking_rule,
)
from artimanager.tracking.runner import run_tracking
from artimanager.validation.manager import create_validation, get_validations, update_validation_outcome
from artimanager.zotero.client import ZoteroClient
from artimanager.relationships.manager import (
    create_relationship,
    delete_relationship,
    get_relationships,
    update_relationship_status,
)
from artimanager.relationships.suggest import suggest_relationships
from artimanager.zotero.linker import (
    get_zotero_link,
    link_paper_to_zotero,
    read_zotero_notes,
    sync_paper_metadata,
)


@click.group()
def cli() -> None:
    """ArtiManager — personal literature workspace."""


@cli.command()
@click.option(
    "--config", "-c",
    "config_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to config.toml",
)
def scan(config_path: str) -> None:
    """Scan configured folders and ingest PDFs into the library."""
    cfg = load_config(config_path)
    init_db(cfg.db_path)
    conn = get_connection(cfg.db_path)

    progress = None
    if sys.stdout.isatty():
        click.echo("Scanning PDFs...")

        def _progress(candidate):  # noqa: ANN001
            click.echo(f"  Processing: {candidate.filename}")

        progress = _progress

    try:
        report = run_intake(cfg, conn, progress=progress)
    finally:
        conn.close()

    summary_parts = [
        f"{report.new_count} new",
        f"{report.duplicate_count} duplicate",
    ]
    if report.updated_count or report.unchanged_count:
        summary_parts.extend([
            f"{report.updated_count} updated",
            f"{report.unchanged_count} unchanged",
        ])
    summary_parts.append(f"{report.failed_count} failed")
    click.echo(f"Scan complete: {', '.join(summary_parts)} (total {report.total})")

    for d in report.details:
        marker = {
            "new": "+",
            "duplicate": "=",
            "updated": "~",
            "unchanged": "-",
            "failed": "!",
        }[d.status]
        line = f"  [{marker}] {d.path}"
        if d.message:
            line += f"  ({d.message})"
        click.echo(line)


@cli.command()
@click.option(
    "--config", "-c",
    "config_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to config.toml",
)
@click.option("--json-output", is_flag=True, help="Output as JSON")
def inbox(config_path: str, json_output: bool) -> None:
    """List papers currently in the inbox."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        rows = conn.execute(
            """
            SELECT p.paper_id, p.title, p.authors, p.year, p.doi, p.arxiv_id,
                   COUNT(f.file_id) AS file_count
            FROM papers p
            LEFT JOIN file_assets f ON f.paper_id = p.paper_id
            WHERE p.workflow_status = 'inbox'
            GROUP BY p.paper_id
            ORDER BY p.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        click.echo("Inbox is empty.")
        return

    if json_output:
        items = []
        for r in rows:
            items.append({
                "paper_id": r[0],
                "title": r[1],
                "authors": json.loads(r[2]) if r[2] else [],
                "year": r[3],
                "doi": r[4],
                "arxiv_id": r[5],
                "file_count": r[6],
            })
        click.echo(json.dumps(items, indent=2, ensure_ascii=False))
        return

    click.echo(f"Inbox: {len(rows)} paper(s)\n")
    for r in rows:
        title = r[1] or "(untitled)"
        authors = json.loads(r[2]) if r[2] else []
        year = r[3] or "?"
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += " et al."

        click.echo(f"  {title}")
        click.echo(f"    Authors: {author_str or '(unknown)'}")
        click.echo(f"    Year: {year}  |  Files: {r[6]}")
        if r[4]:
            click.echo(f"    DOI: {r[4]}")
        if r[5]:
            click.echo(f"    arXiv: {r[5]}")
        click.echo(f"    ID: {r[0]}")
        click.echo()


@cli.command("paper-update")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to update")
@click.option("--workflow-status", type=click.Choice(WORKFLOW_STATUS_VALUES), default=None)
@click.option("--reading-state", type=click.Choice(READING_STATE_VALUES), default=None)
@click.option("--research-state", type=click.Choice(RESEARCH_STATE_VALUES), default=None)
@click.option("--title", default=None, help="Corrected paper title")
@click.option("--authors", default=None, help="Authors separated by comma, semicolon, or newline")
@click.option("--year", default=None, type=int, help="Publication year")
@click.option("--doi", default=None, help="DOI")
@click.option("--arxiv-id", default=None, help="arXiv ID")
@click.option("--abstract", default=None, help="Abstract text")
def paper_update(
    config_path: str,
    paper_id: str,
    workflow_status: str | None,
    reading_state: str | None,
    research_state: str | None,
    title: str | None,
    authors: str | None,
    year: int | None,
    doi: str | None,
    arxiv_id: str | None,
    abstract: str | None,
) -> None:
    """Update paper triage states or manually correct metadata."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    metadata_updates = {
        key: value
        for key, value in {
            "title": title,
            "authors": authors,
            "year": year,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "abstract": abstract,
        }.items()
        if value is not None
    }
    state_requested = any(
        value is not None
        for value in (workflow_status, reading_state, research_state)
    )
    if not state_requested and not metadata_updates:
        click.echo("Error: no paper fields provided.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    changed: dict[str, object] = {}
    try:
        if state_requested:
            changed.update(update_paper_state(
                conn,
                paper_id,
                workflow_status=workflow_status,
                reading_state=reading_state,
                research_state=research_state,
            ))
        if metadata_updates:
            changed.update(update_paper_metadata(conn, paper_id, **metadata_updates))
            index_paper(conn, paper_id)
        conn.commit()
    except (sqlite3.Error, ValueError) as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(f"Paper updated: {paper_id}")
    for field in changed:
        click.echo(f"  {field}")


@cli.command()
@click.argument("query")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--filter-status", default=None, help="Comma-separated workflow statuses")
@click.option("--filter-reading", default=None, help="Comma-separated reading states")
@click.option("--filter-year-min", default=None, type=int, help="Minimum year")
@click.option("--filter-year-max", default=None, type=int, help="Maximum year")
@click.option("--filter-tags", default=None, help="Comma-separated tag names")
@click.option("--source", default="all", type=click.Choice(["metadata", "fulltext", "note", "all"]),
              help="Search source")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.option("--limit", default=20, type=int, help="Max results")
def search(query: str, config_path: str, filter_status: str | None,
           filter_reading: str | None, filter_year_min: int | None,
           filter_year_max: int | None, filter_tags: str | None, source: str,
           json_output: bool, limit: int) -> None:
    """Search the paper library."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    filters = SearchFilters(
        workflow_status=filter_status.split(",") if filter_status else None,
        reading_state=filter_reading.split(",") if filter_reading else None,
        year_min=filter_year_min,
        year_max=filter_year_max,
        tags=[tag.strip() for tag in filter_tags.split(",")] if filter_tags else None,
    )

    conn = get_connection(cfg.db_path)
    try:
        if source == "metadata":
            results = search_papers(conn, query, filters)[:limit]
        elif source == "fulltext":
            results = search_fulltext(conn, query, filters)[:limit]
        elif source == "note":
            results = search_notes(conn, query, filters)[:limit]
        else:
            results = search_all(conn, query, filters, limit=limit)
    finally:
        conn.close()

    if not results:
        click.echo("No results found.")
        return

    if json_output:
        items = [
            {"paper_id": r.paper_id, "title": r.title, "authors": r.authors,
             "year": r.year, "match_source": r.match_source,
             "snippet": r.snippet, "score": r.score}
            for r in results
        ]
        click.echo(json.dumps(items, indent=2, ensure_ascii=False))
        return

    click.echo(f"Found {len(results)} result(s)\n")
    for r in results:
        author_str = ", ".join(r.authors[:3])
        if len(r.authors) > 3:
            author_str += " et al."
        click.echo(f"  {r.title or '(untitled)'}")
        click.echo(f"    Authors: {author_str or '(unknown)'}  |  Year: {r.year or '?'}")
        click.echo(f"    Source: {r.match_source}  |  Score: {r.score:.2f}")
        if r.snippet:
            click.echo(f"    Snippet: {r.snippet}")
        click.echo(f"    ID: {r.paper_id}")
        click.echo()


@cli.command()
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
def reindex(config_path: str) -> None:
    """Rebuild FTS5 search indexes from source data."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        report = rebuild_search_index(conn)
    finally:
        conn.close()

    click.echo(f"Reindex complete: {report.papers_indexed} papers, "
               f"{report.fulltext_indexed} fulltext entries indexed.")


@cli.command("web")
@click.option(
    "--config", "-c",
    "config_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to config.toml",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Host interface to bind")
@click.option("--port", default=8000, type=int, show_default=True, help="Port to bind")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def web(config_path: str, host: str, port: int, reload: bool) -> None:
    """Launch local web workbench."""
    cfg = load_config(config_path)
    try:
        import uvicorn
    except ImportError:
        click.echo("Error: uvicorn is required for `web`. Install project dependencies first.", err=True)
        sys.exit(1)

    os.environ["ARTIMANAGER_WEB_CONFIG"] = str(Path(config_path).resolve())
    click.echo(f"Starting web workbench at http://{host}:{port}")
    uvicorn.run(
        "artimanager.web.app:create_app_from_env",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


# ---------------------------------------------------------------------------
# Discovery commands
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", default=None, help="Library paper ID to anchor discovery")
@click.option("--topic", default=None, help="Free-text topic/keyword to search")
@click.option("--source", default="all",
              type=click.Choice(["semantic_scholar", "arxiv", "deepxiv", "all"]),
              help="Discovery source")
@click.option("--limit", default=20, type=int, help="Max results per source")
def discover(config_path: str, paper_id: str | None, topic: str | None,
             source: str, limit: int) -> None:
    """Discover related papers from online sources."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        report = run_discovery(
            conn,
            paper_id=paper_id,
            topic=topic,
            source=source,
            limit=limit,
            deepxiv_config=cfg.deepxiv,
        )
    except (ValueError, RuntimeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(f"Discovery complete: {report.new_count} new, "
               f"{report.duplicate_count} duplicate, "
               f"{report.error_count} error "
               f"(total {report.total})")

    for r in report.records:
        author_str = ", ".join(r.authors[:3])
        if len(r.authors) > 3:
            author_str += " et al."
        click.echo(f"  [+] {r.title}")
        click.echo(f"      Authors: {author_str or '(unknown)'}  |  Year: {r.published_at or '?'}")
        click.echo(f"      Source: {r.source}  |  External ID: {r.external_id}")
        click.echo()


@cli.command("discovery-inbox")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--status", default=None,
              type=click.Choice(["new", "reviewed", "saved", "ignored", "imported"]),
              help="Filter by status")
@click.option("--trigger-type", default=None,
              type=click.Choice(["paper_anchor", "topic_anchor", "tracking_rule"]),
              help="Filter by trigger type")
@click.option("--trigger-ref", default=None, help="Filter by trigger reference")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.option("--limit", default=50, type=int, help="Max results")
def discovery_inbox(config_path: str, status: str | None, trigger_type: str | None,
                    trigger_ref: str | None, json_output: bool, limit: int) -> None:
    """List discovery results awaiting review."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        sql = (
            "SELECT discovery_result_id, title, authors, published_at, source, external_id, "
            "status, review_action, trigger_type, trigger_ref "
            "FROM discovery_results"
        )
        clauses: list[str] = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if trigger_type:
            clauses.append("trigger_type = ?")
            params.append(trigger_type)
        if trigger_ref:
            clauses.append("trigger_ref = ?")
            params.append(trigger_ref)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        provenance_by_result = (
            list_discovery_sources(conn, [r[0] for r in rows])
            if json_output
            else {}
        )
    finally:
        conn.close()

    if not rows:
        click.echo("Discovery inbox is empty.")
        return

    if json_output:
        items = []
        for r in rows:
            items.append({
                "discovery_result_id": r[0],
                "title": r[1],
                "authors": json.loads(r[2]) if r[2] else [],
                "year": r[3],
                "source": r[4],
                "external_id": r[5],
                "status": r[6],
                "review_action": r[7],
                "trigger_type": r[8],
                "trigger_ref": r[9],
                "provenance": provenance_by_result.get(r[0], []),
            })
        click.echo(json.dumps(items, indent=2, ensure_ascii=False))
        return

    click.echo(f"Discovery inbox: {len(rows)} result(s)\n")
    for r in rows:
        authors = json.loads(r[2]) if r[2] else []
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += " et al."
        click.echo(f"  [{r[6]}] {r[1] or '(untitled)'}")
        click.echo(f"      Authors: {author_str or '(unknown)'}  |  Year: {r[3] or '?'}")
        click.echo(f"      Source: {r[4]}  |  External ID: {r[5]}")
        click.echo(f"      Trigger: {r[8]} / {r[9] or '(none)'}")
        if r[7]:
            click.echo(f"      Action: {r[7]}")
        click.echo(f"      ID: {r[0]}")
        click.echo()


@cli.command("discovery-review")
@click.argument("result_id")
@click.argument("action", type=click.Choice([
    "ignore", "save_for_later", "import", "link_to_existing",
    "follow_author", "mute_topic", "snooze",
]))
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--link-to-paper", default=None, help="Paper ID to link to (for link_to_existing)")
@click.option("--author-name", default=None, help="Author name for follow_author")
def discovery_review(result_id: str, action: str, config_path: str,
                     link_to_paper: str | None, author_name: str | None) -> None:
    """Review a discovery result and take an action."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        outcome = review_discovery_result(
            conn,
            cfg,
            result_id=result_id,
            action=action,
            link_to_paper=link_to_paper,
            author_name=author_name,
        )
        conn.commit()
        click.echo(outcome.message)
    except ValueError as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tracking commands
# ---------------------------------------------------------------------------

@cli.command("tracking-create")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--name", required=True, help="Tracking rule name")
@click.option("--type", "rule_type", required=True,
              type=click.Choice(["keyword", "topic", "author", "category", "citation", "openalex_author"]),
              help="Tracking rule type")
@click.option("--query", default=None, help="Tracking query")
@click.option("--paper-id", default=None, help="Anchor paper ID for citation rules")
@click.option(
    "--direction",
    default=None,
    type=click.Choice(["cited_by", "references"]),
    help="Citation direction for citation rules",
)
@click.option("--limit", default=20, type=int, help="Rule-level fetch limit")
@click.option("--author-id", default=None, help="Stable OpenAlex author ID for openalex_author rules")
@click.option("--display-name", default=None, help="Optional OpenAlex author display metadata")
@click.option("--schedule", default=None, help="Schedule label (defaults to config)")
def tracking_create(config_path: str, name: str, rule_type: str,
                    query: str | None, paper_id: str | None,
                    direction: str | None, limit: int,
                    author_id: str | None, display_name: str | None,
                    schedule: str | None) -> None:
    """Create a tracking rule."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    resolved_schedule = schedule or cfg.tracking_schedule
    conn = get_connection(cfg.db_path)
    try:
        if rule_type == "citation":
            has_anchor_flags = paper_id is not None or direction is not None
            if query and has_anchor_flags:
                raise ValueError(
                    "Citation tracking accepts either --query JSON or --paper-id/--direction, not both"
                )
            if not query:
                if not paper_id or not direction:
                    raise ValueError(
                        "Citation tracking requires --paper-id and --direction when --query is not used"
                    )
                query = serialize_citation_tracking_query(
                    conn,
                    paper_id=paper_id,
                    direction=direction,
                    limit=limit,
                )
        elif rule_type == "openalex_author":
            has_openalex_flags = author_id is not None or display_name is not None
            if query and has_openalex_flags:
                raise ValueError(
                    "OpenAlex author tracking accepts either --query JSON or --author-id/--display-name, not both"
                )
            if not query:
                if not author_id:
                    raise ValueError(
                        "OpenAlex author tracking requires --author-id when --query is not used"
                    )
                query = serialize_openalex_author_tracking_query(
                    author_id=author_id,
                    display_name=display_name,
                    limit=limit,
                )
        elif not query:
            raise ValueError(f"{rule_type} tracking requires --query")
        rule = create_tracking_rule(
            conn,
            name=name,
            rule_type=rule_type,
            query=query,
            schedule=resolved_schedule,
            enabled=True,
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(f"Tracking rule created: {rule.tracking_rule_id}")
    click.echo(f"  Name: {rule.name}")
    click.echo(f"  Type: {rule.rule_type}")
    click.echo(f"  Query: {rule.query}")
    click.echo(f"  Schedule: {rule.schedule or '(none)'}")
    click.echo(f"  Enabled: {rule.enabled}")


@cli.command("tracking-list")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--enabled", default=None, type=click.Choice(["true", "false"]),
              help="Filter enabled state")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def tracking_list(config_path: str, enabled: str | None, json_output: bool) -> None:
    """List tracking rules."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    enabled_filter = None
    if enabled is not None:
        enabled_filter = enabled == "true"

    conn = get_connection(cfg.db_path)
    try:
        rules = list_tracking_rules(conn, enabled=enabled_filter)
    finally:
        conn.close()

    if not rules:
        click.echo("No tracking rules found.")
        return

    if json_output:
        click.echo(json.dumps([
            {
                "tracking_rule_id": r.tracking_rule_id,
                "name": r.name,
                "rule_type": r.rule_type,
                "query": r.query,
                "schedule": r.schedule,
                "enabled": r.enabled,
                "created_at": r.created_at,
            }
            for r in rules
        ], indent=2, ensure_ascii=False))
        return

    click.echo(f"Tracking rules: {len(rules)}\n")
    for r in rules:
        click.echo(f"  [{r.tracking_rule_id}] {r.name}")
        click.echo(f"    Type: {r.rule_type}")
        click.echo(f"    Query: {r.query}")
        click.echo(f"    Schedule: {r.schedule or '(none)'}")
        click.echo(f"    Enabled: {r.enabled}")
        click.echo()


@cli.command("tracking-update")
@click.argument("tracking_rule_id")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--name", default=None, help="Update rule name")
@click.option("--query", default=None, help="Update query")
@click.option("--schedule", default=None, help="Update schedule")
@click.option("--enable/--disable", "enabled", default=None, help="Enable or disable rule")
def tracking_update(
    tracking_rule_id: str,
    config_path: str,
    name: str | None,
    query: str | None,
    schedule: str | None,
    enabled: bool | None,
) -> None:
    """Update a tracking rule."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        updated = update_tracking_rule(
            conn,
            tracking_rule_id,
            name=name,
            query=query,
            schedule=schedule,
            enabled=enabled,
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(f"Tracking rule updated: {updated.tracking_rule_id}")
    click.echo(f"  Name: {updated.name}")
    click.echo(f"  Type: {updated.rule_type}")
    click.echo(f"  Query: {updated.query}")
    click.echo(f"  Schedule: {updated.schedule or '(none)'}")
    click.echo(f"  Enabled: {updated.enabled}")


@cli.command("tracking-delete")
@click.argument("tracking_rule_id")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
def tracking_delete(tracking_rule_id: str, config_path: str) -> None:
    """Delete a tracking rule."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        delete_tracking_rule(conn, tracking_rule_id)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()
    click.echo(f"Tracking rule deleted: {tracking_rule_id}")


@cli.command("tracking-run")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--rule-id", "tracking_rule_id", default=None, help="Run one tracking rule by ID")
@click.option("--limit", default=20, type=int, help="Max candidates per rule")
def tracking_run(config_path: str, tracking_rule_id: str | None, limit: int) -> None:
    """Run tracking rules and store candidates in discovery inbox."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        report = run_tracking(conn, cfg, tracking_rule_id=tracking_rule_id, limit=limit)
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(
        f"Tracking run complete: {report.rules_processed} rules, "
        f"{report.new_count} new, {report.duplicate_count} duplicate, "
        f"{report.error_count} error, {report.warning_count} warning "
        f"(total {report.total})"
    )
    for r in report.records:
        click.echo(f"  [+] {r.title} ({r.external_id})")
        click.echo(f"      Trigger: {r.trigger_ref}  |  Score: {r.relevance_score}")
        if r.relevance_context:
            first_line = r.relevance_context.splitlines()[0]
            click.echo(f"      {first_line}")
        click.echo()


# ---------------------------------------------------------------------------
# Note commands
# ---------------------------------------------------------------------------

@cli.command("note-create")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to create note for")
@click.option("--title", default=None, help="Note title (defaults to paper title)")
@click.option(
    "--filename",
    default=None,
    help="Safe Markdown filename under notes_root (defaults to <paper_id>.md)",
)
def note_create(
    config_path: str,
    paper_id: str,
    title: str | None,
    filename: str | None,
) -> None:
    """Create a Markdown note for a paper, initialised from the default template."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        if title is None:
            row = conn.execute(
                "SELECT title FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            title = row[0] if row else ""

        try:
            record = init_note_from_template(
                conn, paper_id, cfg.notes_root, title=title,
                template_path=cfg.template_path if cfg.template_path else None,
                filename=filename,
            )
        except ValueError as exc:
            conn.rollback()
            click.echo(str(exc), err=True)
            sys.exit(1)
        # Make newly created note searchable without requiring manual reindex.
        index_paper(conn, paper_id)
        conn.commit()
        click.echo(f"Note created: {record.note_id}")
        click.echo(f"  Paper: {paper_id}")
        click.echo(f"  Title: {record.title}")
        click.echo(f"  Path:  {record.location}")
    finally:
        conn.close()


@cli.command("note-show")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to show note for")
def note_show(config_path: str, paper_id: str) -> None:
    """Show the Markdown note path and content for a paper."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        record = get_note(conn, paper_id)
        if record is None:
            click.echo(f"No note found for paper {paper_id}. Run 'note-create' first.")
            return

        click.echo(f"Note: {record.note_id}")
        click.echo(f"  Paper: {paper_id}")
        click.echo(f"  Title: {record.title}")
        click.echo(f"  Path:  {record.location}")
        click.echo(f"  Created: {record.created_at}")
        click.echo(f"  Updated: {record.updated_at}")

        note_path = Path(record.location)
        if note_path.exists():
            content = note_path.read_text()
            click.echo(f"\n--- Content ---\n{content}")
        else:
            click.echo(f"\nWarning: note file not found at {record.location}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tag commands
# ---------------------------------------------------------------------------

@cli.command("tag-add")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to attach tag to")
@click.option("--tag", "tag_name", required=True, help="Tag name")
@click.option("--tag-type", default=None, help="Optional tag type")
def tag_add(config_path: str, paper_id: str, tag_name: str, tag_type: str | None) -> None:
    """Attach one user-confirmed tag to a paper."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        try:
            tag = add_tag_to_paper(conn, paper_id, tag_name, tag_type=tag_type)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        conn.commit()
        click.echo(f"Tag added: {tag.name}")
        click.echo(f"  Paper: {paper_id}")
        if tag.tag_type:
            click.echo(f"  Type:  {tag.tag_type}")
    finally:
        conn.close()


@cli.command("tag-remove")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to detach tag from")
@click.option("--tag", "tag_name", required=True, help="Tag name")
def tag_remove(config_path: str, paper_id: str, tag_name: str) -> None:
    """Detach one tag from a paper."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        removed = remove_tag_from_paper(conn, paper_id, tag_name)
        conn.commit()
        if removed:
            click.echo(f"Tag removed: {tag_name}")
            click.echo(f"  Paper: {paper_id}")
        else:
            click.echo(f"No matching tag link found for paper {paper_id}.")
    finally:
        conn.close()


@cli.command("tag-list")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to list tags for")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def tag_list(config_path: str, paper_id: str, json_output: bool) -> None:
    """List tags attached to a paper."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        items = list_tags_for_paper(conn, paper_id)
    finally:
        conn.close()

    if json_output:
        click.echo(json.dumps([
            {
                "tag_id": t.tag_id,
                "name": t.name,
                "tag_type": t.tag_type,
                "source": t.source,
            }
            for t in items
        ], indent=2, ensure_ascii=False))
        return

    if not items:
        click.echo("No tags found.")
        return

    click.echo(f"Tags ({len(items)}):")
    for t in items:
        suffix = f" ({t.tag_type})" if t.tag_type else ""
        click.echo(f"  - {t.name}{suffix}")


# ---------------------------------------------------------------------------
# Validation commands
# ---------------------------------------------------------------------------

@cli.command("validation-create")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to create validation for")
@click.option("--path", default=None, help="Path to code/workspace")
@click.option("--repo-url", default=None, help="Repository URL")
@click.option("--env-note", default=None, help="Environment note")
def validation_create(config_path: str, paper_id: str, path: str | None,
                      repo_url: str | None, env_note: str | None) -> None:
    """Create a validation record for a paper."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        record = create_validation(
            conn, paper_id, path=path, repo_url=repo_url,
            environment_note=env_note,
        )
        conn.commit()
    except (sqlite3.Error, ValueError) as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(f"Validation created: {record.validation_id}")
    click.echo(f"  Paper: {paper_id}")
    click.echo(f"  Outcome: {record.outcome}")
    if record.path:
        click.echo(f"  Path: {record.path}")
    if record.repo_url:
        click.echo(f"  Repo: {record.repo_url}")


@cli.command("validation-update")
@click.argument("validation_id")
@click.option("--outcome", required=True,
              type=click.Choice(["not_attempted", "in_progress", "reproduced",
                                 "partially_reproduced", "failed"]),
              help="Validation outcome")
@click.option("--summary", default=None, help="Summary of results")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
def validation_update(validation_id: str, outcome: str, summary: str | None,
                      config_path: str) -> None:
    """Update the outcome of a validation record."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        update_validation_outcome(conn, validation_id, outcome, summary=summary)
        conn.commit()
        click.echo(f"Validation {validation_id} updated: {outcome}")
        if summary:
            click.echo(f"  Summary: {summary}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Zotero commands
# ---------------------------------------------------------------------------

@cli.command("zotero-link")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to link")
@click.option("--zotero-key", required=True, help="Zotero item key")
@click.option("--library-id", default=None, help="Zotero library ID (overrides config)")
def zotero_link(config_path: str, paper_id: str, zotero_key: str,
                library_id: str | None) -> None:
    """Link a paper to a Zotero item and sync metadata."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    z_cfg = cfg.zotero
    lib_id = library_id or z_cfg.library_id
    api_key = z_cfg.api_key
    if not lib_id:
        click.echo("Zotero library_id not set. Provide --library-id or set [zotero].library_id in config.", err=True)
        sys.exit(1)

    client = ZoteroClient(lib_id, z_cfg.library_type, api_key)
    item = client.get_item(zotero_key)
    if item is None:
        click.echo(f"Zotero item {zotero_key} not found.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        link = link_paper_to_zotero(conn, paper_id, zotero_key, lib_id)
        diff = sync_paper_metadata(conn, paper_id, item)
        conn.commit()

        click.echo(f"Linked paper {paper_id} to Zotero item {zotero_key}")
        if diff:
            click.echo(f"Synced {len(diff)} field(s):")
            for field, (old, new) in diff.items():
                new_preview = str(new)[:60]
                click.echo(f"  {field}: {new_preview}")
        else:
            click.echo("No fields needed updating (all already populated).")
    finally:
        conn.close()


@cli.command("zotero-show")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to show Zotero info for")
def zotero_show(config_path: str, paper_id: str) -> None:
    """Show Zotero link info and bibliography metadata for a paper."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    z_cfg = cfg.zotero
    lib_id = z_cfg.library_id
    api_key = z_cfg.api_key
    if not lib_id:
        click.echo("Zotero library_id not set in config.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        link = get_zotero_link(conn, paper_id)
        if link is None:
            click.echo(f"No Zotero link found for paper {paper_id}. Run 'zotero-link' first.")
            return

        click.echo(f"Zotero link: {link.zotero_item_key}")
        click.echo(f"  Library: {link.zotero_library_id} ({z_cfg.library_type})")
        click.echo(f"  Attachment mode: {link.attachment_mode or 'not set'}")
        click.echo(f"  Last synced: {link.last_synced_at or 'never'}")

        if api_key and lib_id:
            client = ZoteroClient(lib_id, z_cfg.library_type, api_key)
            item = client.get_item(link.zotero_item_key)
            if item:
                click.echo(f"\nZotero item metadata:")
                click.echo(f"  Type: {item.item_type}")
                click.echo(f"  Title: {item.title}")
                creators = item.creators[:3]
                author_str = ", ".join(
                    c.get("lastName") or c.get("name") or str(c)
                    for c in creators if isinstance(c, dict)
                )
                if len(item.creators) > 3:
                    author_str += " et al."
                click.echo(f"  Authors: {author_str or '(unknown)'}")
                click.echo(f"  Date: {item.date or '?'}")
                if item.doi:
                    click.echo(f"  DOI: {item.doi}")
                if item.arxiv_id:
                    click.echo(f"  arXiv: {item.arxiv_id}")
                if item.tags:
                    click.echo(f"  Tags: {', '.join(item.tags)}")

                notes = read_zotero_notes(conn, paper_id, client)
                if notes:
                    click.echo(f"\nZotero notes: {len(notes)}")
                    for n in notes:
                        click.echo(f"  [{n['note_key']}] {len(n['note_html'])} chars")
                else:
                    click.echo("\nZotero notes: none")
    finally:
        conn.close()


@cli.command("zotero-sync")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--dry-run", is_flag=True, help="Show what would be updated without writing")
def zotero_sync(config_path: str, dry_run: bool) -> None:
    """Sync metadata from Zotero for all linked papers."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    z_cfg = cfg.zotero
    lib_id = z_cfg.library_id
    api_key = z_cfg.api_key
    if not lib_id:
        click.echo("Zotero library_id not set in config.", err=True)
        sys.exit(1)

    client = ZoteroClient(lib_id, z_cfg.library_type, api_key)
    conn = get_connection(cfg.db_path)
    try:
        links = conn.execute(
            "SELECT paper_id, zotero_item_key FROM zotero_links"
        ).fetchall()

        if not links:
            click.echo("No Zotero links found. Use 'zotero-link' first.")
            return

        total_fields = 0
        for paper_id, zotero_key in links:
            item = client.get_item(zotero_key)
            if item is None:
                click.echo(f"  [!] {paper_id}: Zotero item {zotero_key} not found")
                continue

            diff = sync_paper_metadata(conn, paper_id, item)
            total_fields += len(diff)

            if diff:
                fields = ", ".join(diff.keys())
                click.echo(f"  [+] {paper_id}: {len(diff)} field(s) — {fields}")
            else:
                click.echo(f"  [=] {paper_id}: up to date")

        if dry_run:
            conn.rollback()
            click.echo(f"\nDry run: {total_fields} field(s) would be updated across {len(links)} paper(s).")
        else:
            conn.commit()
            click.echo(f"\nSync complete: {total_fields} field(s) updated across {len(links)} paper(s).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Analysis commands
# ---------------------------------------------------------------------------

@cli.command("analysis-create")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to analyze")
@click.option("--prompt", default=None, help="Optional analysis focus prompt")
def analysis_create(config_path: str, paper_id: str, prompt: str | None) -> None:
    """Create a single-paper analysis artifact and record."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        record = create_single_analysis(conn, cfg, paper_id, prompt=prompt)
        conn.commit()
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(f"Analysis created: {record.analysis_id}")
    click.echo(f"  Type: {record.analysis_type}")
    click.echo(f"  Paper IDs: {', '.join(record.paper_ids)}")
    click.echo(f"  Provider: {record.provider_id}")
    click.echo(f"  Artifact: {record.content_location}")


@cli.command("analysis-compare")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", "paper_ids", multiple=True, required=True, help="Paper ID to compare")
@click.option("--prompt", default=None, help="Optional comparison focus prompt")
def analysis_compare(config_path: str, paper_ids: tuple[str, ...], prompt: str | None) -> None:
    """Create a multi-paper comparison artifact and record."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)
    if len(paper_ids) < 2 or len(paper_ids) > 5:
        click.echo("analysis-compare requires between 2 and 5 --paper-id values.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        record = create_comparison(conn, cfg, list(paper_ids), prompt=prompt)
        conn.commit()
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(f"Comparison created: {record.analysis_id}")
    click.echo(f"  Type: {record.analysis_type}")
    click.echo(f"  Paper IDs: {', '.join(record.paper_ids)}")
    click.echo(f"  Provider: {record.provider_id}")
    click.echo(f"  Artifact: {record.content_location}")


@cli.command("analysis-list")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", default=None, help="Filter by paper ID")
@click.option("--type", "analysis_type", default=None, help="Filter by analysis type")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.option("--limit", default=50, type=int, help="Max results")
def analysis_list(config_path: str, paper_id: str | None, analysis_type: str | None,
                  json_output: bool, limit: int) -> None:
    """List analysis records."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        records = list_analyses(
            conn,
            paper_id=paper_id,
            analysis_type=analysis_type,
            limit=limit,
        )
    finally:
        conn.close()

    if not records:
        click.echo("No analysis records found.")
        return

    if json_output:
        items = []
        for r in records:
            items.append({
                "analysis_id": r.analysis_id,
                "analysis_type": r.analysis_type,
                "paper_ids": r.paper_ids,
                "prompt_version": r.prompt_version,
                "provider_id": r.provider_id,
                "evidence_scope": r.evidence_scope,
                "content_location": r.content_location,
                "fact_sections": r.fact_sections,
                "inference_sections": r.inference_sections,
                "created_at": r.created_at,
            })
        click.echo(json.dumps(items, indent=2, ensure_ascii=False))
        return

    click.echo(f"Analysis records: {len(records)}\n")
    for r in records:
        click.echo(f"  [{r.analysis_type}] {r.analysis_id}")
        click.echo(f"    Papers: {', '.join(r.paper_ids)}")
        click.echo(f"    Provider: {r.provider_id or '(unknown)'}")
        click.echo(f"    Artifact: {r.content_location or '(none)'}")
        click.echo(f"    Created: {r.created_at}")
        click.echo()


@cli.command("analysis-show")
@click.argument("analysis_id")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def analysis_show(analysis_id: str, config_path: str, json_output: bool) -> None:
    """Show one analysis record and artifact location."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        record = get_analysis(conn, analysis_id)
    finally:
        conn.close()

    if record is None:
        click.echo(f"Analysis record {analysis_id} not found.", err=True)
        sys.exit(1)

    if json_output:
        click.echo(json.dumps({
            "analysis_id": record.analysis_id,
            "analysis_type": record.analysis_type,
            "paper_ids": record.paper_ids,
            "prompt_version": record.prompt_version,
            "provider_id": record.provider_id,
            "evidence_scope": record.evidence_scope,
            "content_location": record.content_location,
            "fact_sections": record.fact_sections,
            "inference_sections": record.inference_sections,
            "created_at": record.created_at,
        }, indent=2, ensure_ascii=False))
        return

    click.echo(f"Analysis: {record.analysis_id}")
    click.echo(f"  Type: {record.analysis_type}")
    click.echo(f"  Papers: {', '.join(record.paper_ids)}")
    click.echo(f"  Provider: {record.provider_id or '(unknown)'}")
    click.echo(f"  Artifact: {record.content_location or '(none)'}")
    click.echo(f"  Created: {record.created_at}")

    if record.content_location:
        path = Path(record.content_location)
        if path.exists():
            click.echo("\n--- Content ---")
            click.echo(path.read_text())


@cli.command("analysis-suggest")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Anchor paper ID")
@click.option("--mode", default="related", type=click.Choice(["related", "follow_up"]),
              help="Suggestion mode")
@click.option("--candidate-paper-id", "candidate_paper_ids", multiple=True,
              help="Optional explicit candidate paper IDs")
@click.option("--limit", default=8, type=int, help="Max suggestions")
def analysis_suggest(config_path: str, paper_id: str, mode: str,
                     candidate_paper_ids: tuple[str, ...], limit: int) -> None:
    """Create agent-inferred relationship suggestions with trace artifact."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        if mode == "related":
            record, rels = suggest_related_work(
                conn, cfg, paper_id,
                candidate_paper_ids=list(candidate_paper_ids),
                limit=limit,
            )
        else:
            record, rels = suggest_follow_up_work(
                conn, cfg, paper_id,
                candidate_paper_ids=list(candidate_paper_ids),
                limit=limit,
            )
        conn.commit()
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        conn.rollback()
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    click.echo(f"Suggestion analysis created: {record.analysis_id}")
    click.echo(f"  Type: {record.analysis_type}")
    click.echo(f"  Provider: {record.provider_id}")
    click.echo(f"  Artifact: {record.content_location}")
    click.echo(f"  Relationships created: {len(rels)}")
    for rel in rels:
        click.echo(
            f"    - {rel.source_paper_id} -> {rel.target_paper_id} "
            f"({rel.relationship_type}, confidence={rel.confidence})"
        )


# ---------------------------------------------------------------------------
# Relationship commands
# ---------------------------------------------------------------------------

@cli.command("relationship-create")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--source-paper", required=True, help="Source paper ID")
@click.option("--target-paper", required=True, help="Target paper ID")
@click.option("--type", "rel_type", required=True,
              type=click.Choice(["prior_work", "follow_up_work", "user_defined"]),
              help="Relationship type")
@click.option("--evidence", default=None, help="Evidence / reason text")
def relationship_create(config_path: str, source_paper: str, target_paper: str,
                        rel_type: str, evidence: str | None) -> None:
    """Create a confirmed relationship between two papers."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        rel = create_relationship(
            conn,
            source_paper_id=source_paper,
            target_paper_id=target_paper,
            relationship_type=rel_type,
            status="confirmed",
            evidence_type="user_asserted",
            evidence_text=evidence,
        )
        conn.commit()
        click.echo(f"Relationship created: {rel.relationship_id}")
        click.echo(f"  Source: {rel.source_paper_id}")
        click.echo(f"  Target: {rel.target_paper_id}")
        click.echo(f"  Type:   {rel.relationship_type}")
    finally:
        conn.close()


@cli.command("relationship-list")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to list relationships for")
@click.option("--direction", default="both",
              type=click.Choice(["both", "outgoing", "incoming"]),
              help="Relationship direction filter")
@click.option("--status", default=None,
              type=click.Choice(["suggested", "confirmed", "rejected"]),
              help="Filter by status")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def relationship_list(config_path: str, paper_id: str, direction: str,
                      status: str | None, json_output: bool) -> None:
    """List relationships for a paper."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        rels = get_relationships(conn, paper_id, direction=direction, status=status)
    finally:
        conn.close()

    if not rels:
        click.echo("No relationships found.")
        return

    if json_output:
        items = [
            {
                "relationship_id": r.relationship_id,
                "source_paper_id": r.source_paper_id,
                "target_paper_id": r.target_paper_id,
                "relationship_type": r.relationship_type,
                "status": r.status,
                "evidence_type": r.evidence_type,
                "evidence_text": r.evidence_text,
                "confidence": r.confidence,
            }
            for r in rels
        ]
        click.echo(json.dumps(items, indent=2, ensure_ascii=False))
        return

    click.echo(f"Relationships: {len(rels)}\n")
    for r in rels:
        click.echo(f"  {r.source_paper_id} → {r.target_paper_id}")
        click.echo(f"    Type:       {r.relationship_type}")
        click.echo(f"    Status:     {r.status}")
        click.echo(f"    Evidence:   {r.evidence_type or '(none)'}")
        if r.evidence_text:
            click.echo(f"    Text:       {r.evidence_text}")
        click.echo(f"    Confidence: {r.confidence}")
        click.echo(f"    ID: {r.relationship_id}")
        click.echo()


@cli.command("relationship-suggest")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
@click.option("--paper-id", required=True, help="Paper ID to suggest relationships for")
def relationship_suggest(config_path: str, paper_id: str) -> None:
    """Suggest relationships for a paper based on metadata similarity."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    conn = get_connection(cfg.db_path)
    try:
        suggestions = suggest_relationships(conn, paper_id)
        conn.commit()
    finally:
        conn.close()

    if not suggestions:
        click.echo("No new suggestions found.")
        return

    click.echo(f"Found {len(suggestions)} suggestion(s):\n")
    for s in suggestions:
        click.echo(f"  {s.source_paper_id} → {s.target_paper_id}")
        click.echo(f"    Type:       {s.relationship_type}")
        click.echo(f"    Confidence: {s.confidence}")
        if s.evidence_text:
            click.echo(f"    Evidence:   {s.evidence_text}")
        click.echo(f"    ID: {s.relationship_id}")
        click.echo()


@cli.command("relationship-review")
@click.argument("relationship_id")
@click.argument("action", type=click.Choice(["confirm", "reject"]))
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to config.toml")
def relationship_review(relationship_id: str, action: str,
                        config_path: str) -> None:
    """Confirm or reject a relationship."""
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        click.echo("Database not found. Run 'scan' first.", err=True)
        sys.exit(1)

    new_status = "confirmed" if action == "confirm" else "rejected"
    conn = get_connection(cfg.db_path)
    try:
        update_relationship_status(conn, relationship_id, new_status)
        conn.commit()
        click.echo(f"Relationship {relationship_id} {action}ed.")
    finally:
        conn.close()


if __name__ == "__main__":
    cli()
