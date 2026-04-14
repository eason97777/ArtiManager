"""Note management — create, retrieve, and initialise notes from templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from artimanager.db.utils import new_id, now_iso


@dataclass
class NoteRecord:
    """A note linked to a paper."""

    note_id: str
    paper_id: str
    note_type: str  # "markdown_note" | "zotero_note" | "annotation_summary"
    location: str  # filesystem path or Zotero key
    title: str
    created_at: str
    updated_at: str
    template_version: str | None = None


def get_note(conn, paper_id: str) -> NoteRecord | None:
    """Return the markdown note for a paper, or None."""
    row = conn.execute(
        "SELECT note_id, paper_id, note_type, location, title, "
        "created_at, updated_at, template_version "
        "FROM notes WHERE paper_id = ? AND note_type = 'markdown_note'",
        (paper_id,),
    ).fetchone()
    if row is None:
        return None
    return NoteRecord(*row)


def create_note(
    conn,
    paper_id: str,
    notes_root: str | Path,
    *,
    note_type: str = "markdown_note",
    title: str = "",
    template_path: str | Path | None = None,
) -> NoteRecord:
    """Create a note for a paper.

    If a markdown note already exists for this paper, returns the existing record.
    If template_path is provided, initialises the note file from that template.
    """
    existing = get_note(conn, paper_id)
    if existing is not None:
        return existing

    now = now_iso()
    note_id = new_id()
    notes_root = Path(notes_root)
    notes_root.mkdir(parents=True, exist_ok=True)
    note_file = notes_root / f"{paper_id}.md"

    if template_path:
        src = Path(template_path)
        if src.exists():
            content = src.read_text()
            # Replace frontmatter placeholders
            content = content.replace('paper_id: ""', f'paper_id: "{paper_id}"')
            content = content.replace('title: ""', f'title: "{title}"')
            content = content.replace('created_at: ""', f'created_at: "{now}"')
            content = content.replace('updated_at: ""', f'updated_at: "{now}"')
            note_file.write_text(content)
        else:
            note_file.write_text(f"# {title or paper_id}\n")
    else:
        note_file.write_text(f"# {title or paper_id}\n")

    template_version = "v2" if template_path else None

    conn.execute(
        """INSERT INTO notes
           (note_id, paper_id, note_type, location, title, created_at, updated_at, template_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (note_id, paper_id, note_type, str(note_file), title, now, now, template_version),
    )

    return NoteRecord(
        note_id=note_id,
        paper_id=paper_id,
        note_type=note_type,
        location=str(note_file),
        title=title,
        created_at=now,
        updated_at=now,
        template_version=template_version,
    )


def init_note_from_template(
    conn,
    paper_id: str,
    notes_root: str | Path,
    title: str = "",
    template_path: str | Path | None = None,
) -> NoteRecord:
    """Create a note from the default template if no template_path given.

    If template_path is None, falls back to the release template under
    ``SourceCode/data``.
    """
    if template_path is None:
        template_path = Path(__file__).resolve().parents[3] / \
            "data" / "paper-note-template.md"
    return create_note(conn, paper_id, notes_root, title=title, template_path=template_path)
