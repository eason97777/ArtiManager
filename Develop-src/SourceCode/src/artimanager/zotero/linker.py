"""Zotero link management — connect papers to Zotero items and sync metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass

from artimanager.db.utils import now_iso


@dataclass
class ZoteroLink:
    """A Zotero link record for a paper."""

    paper_id: str
    zotero_library_id: str
    zotero_item_key: str
    attachment_mode: str | None
    last_synced_at: str | None


def link_paper_to_zotero(
    conn,
    paper_id: str,
    zotero_item_key: str,
    library_id: str,
    attachment_mode: str | None = None,
) -> ZoteroLink:
    """Link a paper to a Zotero item. Upserts if already linked."""
    now = now_iso()
    conn.execute(
        """INSERT INTO zotero_links
           (paper_id, zotero_library_id, zotero_item_key, attachment_mode, last_synced_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(paper_id) DO UPDATE SET
               zotero_library_id = excluded.zotero_library_id,
               zotero_item_key = excluded.zotero_item_key,
               attachment_mode = excluded.attachment_mode,
               last_synced_at = excluded.last_synced_at""",
        (paper_id, library_id, zotero_item_key, attachment_mode, now),
    )
    conn.execute(
        "UPDATE papers SET zotero_item_key = ? WHERE paper_id = ?",
        (zotero_item_key, paper_id),
    )
    return ZoteroLink(
        paper_id=paper_id,
        zotero_library_id=library_id,
        zotero_item_key=zotero_item_key,
        attachment_mode=attachment_mode,
        last_synced_at=now,
    )


def get_zotero_link(conn, paper_id: str) -> ZoteroLink | None:
    """Return the Zotero link for a paper, or None."""
    row = conn.execute(
        "SELECT paper_id, zotero_library_id, zotero_item_key, "
        "attachment_mode, last_synced_at "
        "FROM zotero_links WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        return None
    return ZoteroLink(*row)


def find_paper_by_zotero_key(conn, zotero_key: str) -> str | None:
    """Return the paper_id linked to a Zotero item key, or None."""
    row = conn.execute(
        "SELECT paper_id FROM zotero_links WHERE zotero_item_key = ?",
        (zotero_key,),
    ).fetchone()
    return row[0] if row else None


# Fields that can be synced from Zotero, in priority order.
_SYNC_FIELDS = [
    ("title", "title"),
    ("authors", "creators"),
    ("year", "date"),
    ("doi", "doi"),
    ("arxiv_id", "arxiv_id"),
    ("abstract", "abstract"),
]


def sync_paper_metadata(conn, paper_id: str, item) -> dict:
    """Sync metadata from a ZoteroItem into the paper record.

    Only fills blank (NULL/empty) fields — never overwrites existing values.

    Returns a diff report: {field: (old_value, new_value)} for fields that
    would be updated.
    """
    from artimanager.zotero._models import ZoteroItem

    if not isinstance(item, ZoteroItem):
        raise TypeError(f"Expected ZoteroItem, got {type(item).__name__}")

    row = conn.execute(
        "SELECT title, authors, year, doi, arxiv_id, abstract FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Paper {paper_id} not found")

    current = {
        "title": row[0],
        "authors": row[1],
        "year": row[2],
        "doi": row[3],
        "arxiv_id": row[4],
        "abstract": row[5],
    }

    # Build candidate values from Zotero item
    creators = item.creators or []
    author_names = []
    for c in creators:
        if isinstance(c, dict):
            name = c.get("lastName") or c.get("name") or ""
            first = c.get("firstName") or ""
            if name:
                author_names.append(f"{first} {name}".strip() if first else name)
        elif isinstance(c, str):
            author_names.append(c)
    authors_json = json.dumps(author_names) if author_names else None

    # Parse year from date string (e.g. "2024-03-15" -> 2024)
    year = None
    if item.date:
        year_str = item.date.split("-")[0].strip()
        if year_str.isdigit() and 1000 <= int(year_str) <= 2100:
            year = int(year_str)

    candidates = {
        "title": item.title or None,
        "authors": authors_json,
        "year": year,
        "doi": item.doi,
        "arxiv_id": item.arxiv_id,
        "abstract": item.abstract,
    }

    # Compute diff: only fill blanks
    diff: dict[str, tuple] = {}
    updates = {}
    for field in ("title", "authors", "year", "doi", "arxiv_id", "abstract"):
        old = current[field]
        new = candidates[field]
        if old is None or old == "" or old == "[]":
            if new is not None and new != "":
                diff[field] = (old, new)
                updates[field] = new
        elif field == "authors" and old == "[]":
            if new is not None and new != "":
                diff[field] = (old, new)
                updates[field] = new

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [paper_id]
        conn.execute(f"UPDATE papers SET {set_clause} WHERE paper_id = ?", values)

    # Sync tags: append Zotero tags to paper's existing tags (no dedup at DB level yet)
    # Tags are stored in the tags + paper_tags tables; for now we just record them
    # in the diff report for user review.

    return diff


def read_zotero_notes(conn, paper_id: str, client) -> list[dict]:
    """Read Zotero notes for a paper's linked Zotero item.

    Returns a list of dicts: {note_key, note_html, tags}.
    Does NOT create note records — just returns the raw data for review.
    """
    link = get_zotero_link(conn, paper_id)
    if link is None:
        return []

    raw_children = client.get_children_raw(link.zotero_item_key)
    for child in raw_children:
        data = child.get("data", {})
        if data.get("itemType") == "note":
            notes.append({
                "note_key": child.get("key", ""),
                "note_html": data.get("note", ""),
                "tags": [t["tag"] if isinstance(t, dict) else t for t in data.get("tags", [])],
            })

    return notes
