"""Database schema definitions.

All tables follow the data model defined in docs/data-model.md.
Tables are created with IF NOT EXISTS so init_db is idempotent.
"""

SCHEMA_SQL = """
-- ============================================================
-- Core tables (Phase 0.5)
-- ============================================================

CREATE TABLE IF NOT EXISTS papers (
    paper_id        TEXT PRIMARY KEY,
    title           TEXT,
    authors         TEXT,           -- JSON array of author strings
    year            INTEGER,
    venue           TEXT,           -- reserved for Phase 6+
    abstract        TEXT,
    doi             TEXT,
    arxiv_id        TEXT,
    canonical_source TEXT,          -- reserved for Phase 6+
    zotero_item_key TEXT,
    workflow_status TEXT NOT NULL DEFAULT 'discovered',
    reading_state   TEXT NOT NULL DEFAULT 'to_read',
    research_state  TEXT NOT NULL DEFAULT 'untriaged',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS file_assets (
    file_id             TEXT PRIMARY KEY,
    paper_id            TEXT REFERENCES papers(paper_id),
    absolute_path       TEXT NOT NULL,
    filename            TEXT NOT NULL,
    sha256              TEXT,
    filesize            INTEGER,
    mime_type           TEXT,
    detected_title      TEXT,
    detected_year       INTEGER,
    full_text_extracted  INTEGER NOT NULL DEFAULT 0,
    full_text           TEXT,
    import_status       TEXT NOT NULL DEFAULT 'new',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    tag_id      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    tag_type    TEXT,
    source      TEXT NOT NULL DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS paper_tags (
    paper_id            TEXT NOT NULL REFERENCES papers(paper_id),
    tag_id              TEXT NOT NULL REFERENCES tags(tag_id),
    confidence          REAL,
    confirmed_by_user   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (paper_id, tag_id)
);

-- ============================================================
-- Relationship tables (Phase 6)
-- ============================================================

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id     TEXT PRIMARY KEY,
    source_paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
    target_paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
    relationship_type   TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'suggested',
    evidence_type       TEXT,
    evidence_text       TEXT,
    confidence          REAL,
    created_by          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Zotero integration (Phase 5)
-- ============================================================

CREATE TABLE IF NOT EXISTS zotero_links (
    paper_id            TEXT PRIMARY KEY REFERENCES papers(paper_id),
    zotero_library_id   TEXT,
    zotero_item_key     TEXT NOT NULL,
    attachment_mode     TEXT,
    last_synced_at      TEXT
);

-- ============================================================
-- Notes and validation (Phase 4)
-- ============================================================

CREATE TABLE IF NOT EXISTS notes (
    note_id         TEXT PRIMARY KEY,
    paper_id        TEXT NOT NULL REFERENCES papers(paper_id),
    note_type       TEXT NOT NULL,
    location        TEXT,
    title           TEXT,
    created_by      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    template_version TEXT
);

CREATE TABLE IF NOT EXISTS validation_records (
    validation_id       TEXT PRIMARY KEY,
    paper_id            TEXT NOT NULL REFERENCES papers(paper_id),
    path                TEXT,
    repo_url            TEXT,
    environment_note    TEXT,
    outcome             TEXT NOT NULL DEFAULT 'not_attempted',
    summary             TEXT,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Discovery and tracking (Phase 3 / Phase 9)
-- ============================================================

CREATE TABLE IF NOT EXISTS discovery_results (
    discovery_result_id TEXT PRIMARY KEY,
    trigger_type        TEXT NOT NULL,
    trigger_ref         TEXT,
    source              TEXT NOT NULL,
    external_id         TEXT,
    title               TEXT,
    authors             TEXT,
    abstract            TEXT,
    doi                 TEXT,
    arxiv_id            TEXT,
    published_at        TEXT,
    relevance_score     REAL,
    relevance_context   TEXT,
    status              TEXT NOT NULL DEFAULT 'new',
    review_action       TEXT,
    imported_paper_id   TEXT REFERENCES papers(paper_id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS tracking_rules (
    tracking_rule_id    TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    rule_type           TEXT NOT NULL,
    query               TEXT NOT NULL,
    schedule            TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Agent analysis (Phase 8)
-- ============================================================

CREATE TABLE IF NOT EXISTS analysis_records (
    analysis_id         TEXT PRIMARY KEY,
    analysis_type       TEXT NOT NULL,
    paper_ids           TEXT NOT NULL,       -- JSON array of paper_id strings
    prompt_version      TEXT,
    provider_id         TEXT,
    evidence_scope      TEXT,
    content_location    TEXT,
    fact_sections       TEXT,
    inference_sections  TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_file_assets_sha256 ON file_assets(sha256);
CREATE INDEX IF NOT EXISTS idx_file_assets_paper_id ON file_assets(paper_id);

-- ============================================================
-- FTS5 virtual tables (Phase 2 — Local Search)
-- ============================================================

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts
    USING fts5(paper_id UNINDEXED, title, authors, abstract);

CREATE VIRTUAL TABLE IF NOT EXISTS fulltext_fts
    USING fts5(paper_id UNINDEXED, full_text);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
    USING fts5(paper_id UNINDEXED, note_title, note_content);
"""
