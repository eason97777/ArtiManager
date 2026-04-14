"""Relationship suggestion pipeline — rule-based relationship proposals."""

from __future__ import annotations

import re
import sqlite3

from artimanager.relationships.manager import RelationshipRecord, create_relationship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_title(title: str) -> str:
    """Lowercase, strip punctuation and whitespace for fuzzy compare."""
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _word_tokens(title: str) -> set[str]:
    """Return lowercased word tokens from a title string."""
    return set(title.lower().split())


def _token_overlap(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Compute overlap ratio: |intersection| / max(|a|, |b|)."""
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))


def _load_existing_pairs(
    conn: sqlite3.Connection,
    paper_id: str,
) -> set[tuple[str, str]]:
    """Return all existing relationship pairs involving *paper_id* (both directions)."""
    rows = conn.execute(
        "SELECT source_paper_id, target_paper_id FROM relationships "
        "WHERE source_paper_id = ? OR target_paper_id = ?",
        (paper_id, paper_id),
    ).fetchall()
    pairs: set[tuple[str, str]] = set()
    for r in rows:
        pairs.add((r[0], r[1]))
        pairs.add((r[1], r[0]))
    return pairs


def _pair_exists(
    existing: set[tuple[str, str]],
    source_id: str,
    target_id: str,
) -> bool:
    """Check whether a relationship already exists between two papers."""
    return (source_id, target_id) in existing or (target_id, source_id) in existing


# ---------------------------------------------------------------------------
# Individual strategies
# ---------------------------------------------------------------------------


def _strategy_citation(
    conn: sqlite3.Connection,
    paper_id: str,
    existing: set[tuple[str, str]],
) -> list[RelationshipRecord]:
    """Strategy 1: Citation-based suggestions from discovery_results."""
    rows = conn.execute(
        "SELECT imported_paper_id FROM discovery_results "
        "WHERE trigger_type = 'paper_anchor' "
        "AND trigger_ref = ? "
        "AND status = 'imported' "
        "AND imported_paper_id IS NOT NULL",
        (paper_id,),
    ).fetchall()

    results: list[RelationshipRecord] = []
    for (target_id,) in rows:
        if target_id == paper_id:
            continue
        if _pair_exists(existing, paper_id, target_id):
            continue
        rec = create_relationship(
            conn,
            paper_id,
            target_id,
            "prior_work",
            evidence_type="citation_based",
            created_by="suggest_pipeline",
            status="suggested",
        )
        results.append(rec)
        existing.add((paper_id, target_id))
        existing.add((target_id, paper_id))
    return results


def _strategy_shared_identifiers(
    conn: sqlite3.Connection,
    paper_id: str,
    existing: set[tuple[str, str]],
) -> list[RelationshipRecord]:
    """Strategy 2: Shared DOI prefix or arXiv category prefix."""
    # Fetch the source paper's identifiers and year.
    source = conn.execute(
        "SELECT doi, arxiv_id, year FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if source is None:
        return []

    source_doi, source_arxiv, source_year = source

    results: list[RelationshipRecord] = []

    # --- DOI prefix matching ---
    if source_doi:
        # Extract prefix: everything before the second '/'
        # e.g. "10.1234/xyz.abc" -> "10.1234"
        parts = source_doi.split("/", 2)
        if len(parts) >= 2:
            doi_prefix = parts[0]  # "10.1234"
            rows = conn.execute(
                "SELECT paper_id, doi, year FROM papers "
                "WHERE doi IS NOT NULL AND paper_id != ?",
                (paper_id,),
            ).fetchall()
            for pid, doi, year in rows:
                if _pair_exists(existing, paper_id, pid):
                    continue
                other_parts = doi.split("/", 2)
                if len(other_parts) >= 2 and other_parts[0] == doi_prefix:
                    rel_type = _year_based_type(source_year, year)
                    rec = create_relationship(
                        conn,
                        paper_id,
                        pid,
                        rel_type,
                        evidence_type="metadata_match",
                        created_by="suggest_pipeline",
                        status="suggested",
                    )
                    results.append(rec)
                    existing.add((paper_id, pid))
                    existing.add((pid, paper_id))

    # --- arXiv category prefix matching ---
    if source_arxiv:
        # First 5 chars, e.g. "2401." for same month batch
        arxiv_prefix = source_arxiv[:5]
        rows = conn.execute(
            "SELECT paper_id, arxiv_id, year FROM papers "
            "WHERE arxiv_id IS NOT NULL AND paper_id != ?",
            (paper_id,),
        ).fetchall()
        for pid, arxiv_id, year in rows:
            if _pair_exists(existing, paper_id, pid):
                continue
            if arxiv_id[:5] == arxiv_prefix:
                rel_type = _year_based_type(source_year, year)
                rec = create_relationship(
                    conn,
                    paper_id,
                    pid,
                    rel_type,
                    evidence_type="metadata_match",
                    created_by="suggest_pipeline",
                    status="suggested",
                )
                results.append(rec)
                existing.add((paper_id, pid))
                existing.add((pid, paper_id))

    return results


def _year_based_type(source_year: int | None, target_year: int | None) -> str:
    """Determine relationship type based on year ordering.

    - target_year < source_year or target_year is None -> prior_work
    - target_year > source_year -> follow_up_work
    - same year -> prior_work
    """
    if source_year is None or target_year is None:
        return "prior_work"
    if target_year > source_year:
        return "follow_up_work"
    return "prior_work"


def _strategy_title_similarity(
    conn: sqlite3.Connection,
    paper_id: str,
    existing: set[tuple[str, str]],
) -> list[RelationshipRecord]:
    """Strategy 3: Title similarity via word-token overlap."""
    source = conn.execute(
        "SELECT title FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if source is None or source[0] is None:
        return []

    source_title: str = source[0]
    source_tokens = _word_tokens(source_title)
    if not source_tokens:
        return []

    rows = conn.execute(
        "SELECT paper_id, title FROM papers "
        "WHERE title IS NOT NULL AND paper_id != ?",
        (paper_id,),
    ).fetchall()

    results: list[RelationshipRecord] = []
    for pid, title in rows:
        if _pair_exists(existing, paper_id, pid):
            continue
        target_tokens = _word_tokens(title)
        if _token_overlap(source_tokens, target_tokens) > 0.6:
            rec = create_relationship(
                conn,
                paper_id,
                pid,
                "prior_work",
                evidence_type="metadata_match",
                created_by="suggest_pipeline",
                status="suggested",
            )
            results.append(rec)
            existing.add((paper_id, pid))
            existing.add((pid, paper_id))

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def suggest_relationships(
    conn: sqlite3.Connection,
    paper_id: str,
) -> list[RelationshipRecord]:
    """Run the relationship suggestion pipeline for *paper_id*.

    Executes three strategies in order:
    1. Citation-based (from discovery_results)
    2. Shared identifiers (DOI prefix, arXiv category prefix)
    3. Title similarity (word-token overlap > 0.6)

    All suggestions are created with ``status='suggested'`` and
    ``created_by='suggest_pipeline'``.  Pairs that already have a
    relationship record (any status, any direction) are skipped.

    Returns the list of newly created :class:`RelationshipRecord` objects.
    """
    existing = _load_existing_pairs(conn, paper_id)

    suggestions: list[RelationshipRecord] = []
    suggestions.extend(_strategy_citation(conn, paper_id, existing))
    suggestions.extend(_strategy_shared_identifiers(conn, paper_id, existing))
    suggestions.extend(_strategy_title_similarity(conn, paper_id, existing))

    return suggestions
