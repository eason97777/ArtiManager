"""Tests for search.query — FTS5 search functions."""

from __future__ import annotations

import json
import sqlite3

import pytest

from artimanager.search.indexer import rebuild_search_index
from artimanager.search.query import (
    SearchFilters,
    SearchResult,
    search_all,
    search_fulltext,
    search_notes,
    search_papers,
)


def _seed_data(conn: sqlite3.Connection) -> None:
    """Insert test papers and file assets, then build FTS index."""
    conn.execute(
        """INSERT INTO papers
           (paper_id, title, authors, year, abstract, workflow_status, reading_state)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("p1", "Deep Learning for NLP",
         json.dumps(["Alice Smith", "Bob Jones"]), 2021,
         "We present a deep learning approach to natural language processing.",
         "inbox", "to_read"),
    )
    conn.execute(
        """INSERT INTO papers
           (paper_id, title, authors, year, abstract, workflow_status, reading_state)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("p2", "Reinforcement Learning in Robotics",
         json.dumps(["Carol White"]), 2023,
         "This paper surveys reinforcement learning methods for robotic control.",
         "confirmed", "reading"),
    )
    conn.execute(
        """INSERT INTO file_assets
           (file_id, paper_id, absolute_path, filename, full_text_extracted, full_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("f1", "p1", "/tmp/p1.pdf", "p1.pdf", 1,
         "Deep learning has revolutionized natural language processing tasks."),
    )
    conn.execute(
        """INSERT INTO file_assets
           (file_id, paper_id, absolute_path, filename, full_text_extracted, full_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("f2", "p2", "/tmp/p2.pdf", "p2.pdf", 1,
         "Reinforcement learning enables robots to learn from trial and error."),
    )
    conn.execute(
        "INSERT INTO tags (tag_id, name, tag_type, source) VALUES (?, ?, ?, ?)",
        ("t1", "Graph ML", "topic", "user"),
    )
    conn.execute(
        "INSERT INTO paper_tags (paper_id, tag_id, confidence, confirmed_by_user) VALUES (?, ?, ?, ?)",
        ("p1", "t1", None, 1),
    )
    conn.commit()
    rebuild_search_index(conn)


def _seed_note_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO notes_fts (paper_id, note_title, note_content) VALUES (?, ?, ?)",
        ("p1", "Paper Note", "My reading note mentions gated graph networks."),
    )
    conn.commit()


class TestSearchPapers:
    def test_finds_by_title(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_papers(db_conn, "deep learning")
        assert len(results) >= 1
        assert results[0].paper_id == "p1"
        assert results[0].match_source == "metadata"

    def test_finds_by_author(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_papers(db_conn, "Alice Smith")
        assert len(results) >= 1
        assert results[0].paper_id == "p1"

    def test_finds_by_abstract(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_papers(db_conn, "reinforcement learning methods")
        assert len(results) >= 1
        assert results[0].paper_id == "p2"

    def test_no_match(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_papers(db_conn, "quantum computing")
        assert results == []

    def test_score_positive(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_papers(db_conn, "learning")
        assert all(r.score > 0 for r in results)


class TestSearchFulltext:
    def test_finds_in_fulltext(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_fulltext(db_conn, "revolutionized")
        assert len(results) == 1
        assert results[0].paper_id == "p1"
        assert results[0].match_source == "fulltext"

    def test_finds_robot_content(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_fulltext(db_conn, "robots")
        assert len(results) >= 1
        assert results[0].paper_id == "p2"


class TestSearchNotes:
    def test_returns_note_hits(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        _seed_note_index(db_conn)
        results = search_notes(db_conn, "gated graph")
        assert len(results) == 1
        assert results[0].paper_id == "p1"
        assert results[0].match_source == "note"


class TestSearchAll:
    def test_combines_sources(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_all(db_conn, "learning")
        assert len(results) >= 1
        paper_ids = {r.paper_id for r in results}
        assert "p1" in paper_ids

    def test_groups_by_paper(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_all(db_conn, "learning")
        paper_ids = [r.paper_id for r in results]
        assert len(paper_ids) == len(set(paper_ids))

    def test_respects_limit(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_all(db_conn, "learning", limit=1)
        assert len(results) <= 1

    def test_includes_note_hits(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        _seed_note_index(db_conn)
        results = search_all(db_conn, "gated graph", limit=5)
        assert len(results) == 1
        assert results[0].paper_id == "p1"
        assert results[0].match_source == "note"


class TestSearchFilters:
    def test_filter_by_workflow_status(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        filters = SearchFilters(workflow_status=["inbox"])
        results = search_papers(db_conn, "learning", filters)
        assert all(r.paper_id == "p1" for r in results)

    def test_filter_by_reading_state(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        filters = SearchFilters(reading_state=["reading"])
        results = search_papers(db_conn, "learning", filters)
        assert all(r.paper_id == "p2" for r in results)

    def test_filter_by_year_range(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        filters = SearchFilters(year_min=2022)
        results = search_papers(db_conn, "learning", filters)
        assert all(r.paper_id == "p2" for r in results)

    def test_no_filters(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        results = search_papers(db_conn, "learning", None)
        assert len(results) >= 2

    def test_filter_by_tags(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        filters = SearchFilters(tags=["graph ml"])
        results = search_papers(db_conn, "learning", filters)
        assert len(results) >= 1
        assert all(r.paper_id == "p1" for r in results)

    def test_filter_by_tags_normalizes_whitespace_and_case(self, db_conn: sqlite3.Connection) -> None:
        _seed_data(db_conn)
        filters = SearchFilters(tags=["  GRAPH   ML  "])
        results = search_papers(db_conn, "learning", filters)
        assert len(results) >= 1
        assert all(r.paper_id == "p1" for r in results)
