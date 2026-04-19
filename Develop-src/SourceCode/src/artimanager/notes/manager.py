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


def _get_markdown_note_by_id(conn, paper_id: str, note_id: str) -> NoteRecord | None:
    row = conn.execute(
        "SELECT note_id, paper_id, note_type, location, title, "
        "created_at, updated_at, template_version "
        "FROM notes WHERE paper_id = ? AND note_id = ? AND note_type = 'markdown_note'",
        (paper_id, note_id),
    ).fetchone()
    if row is None:
        return None
    return NoteRecord(*row)


def safe_markdown_filename(raw: str | None, default_stem: str) -> str:
    """Return a safe Markdown filename, defaulting only when raw is omitted."""
    if raw is None:
        raw_name = default_stem
    else:
        raw_name = raw.strip()
        if not raw_name:
            raise ValueError("Markdown note filename cannot be empty.")

    filename = raw_name.strip()
    if not filename:
        raise ValueError("Markdown note filename cannot be empty.")
    if Path(filename).is_absolute():
        raise ValueError("Markdown note filename must not be an absolute path.")
    if filename.startswith("."):
        raise ValueError("Markdown note filename must not start with '.'.")
    if "/" in filename or "\\" in filename:
        raise ValueError("Markdown note filename must not contain path separators.")
    if ".." in filename:
        raise ValueError("Markdown note filename must not contain '..'.")

    path = Path(filename)
    if path.suffix:
        if path.suffix.lower() != ".md":
            raise ValueError("Markdown note filename must use the .md extension.")
    else:
        filename = f"{filename}.md"
        path = Path(filename)

    if path.name != filename or path.name in {"", ".", "..", ".md"}:
        raise ValueError("Markdown note filename is not valid.")
    return filename


def _markdown_note_path(notes_root: str | Path, filename: str) -> Path:
    root = Path(notes_root)
    target = root / filename
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Markdown note path must stay under notes_root.") from exc
    return target


def create_note(
    conn,
    paper_id: str,
    notes_root: str | Path,
    *,
    note_type: str = "markdown_note",
    title: str = "",
    template_path: str | Path | None = None,
    filename: str | None = None,
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
    safe_filename = safe_markdown_filename(filename, paper_id)
    note_file = _markdown_note_path(notes_root, safe_filename)
    if note_file.exists():
        raise ValueError(f"Markdown note file already exists: {note_file}")

    if template_path:
        src = Path(template_path)
        if src.exists():
            content = src.read_text(encoding="utf-8")
            # Replace frontmatter placeholders
            content = content.replace('paper_id: ""', f'paper_id: "{paper_id}"')
            content = content.replace('title: ""', f'title: "{title}"')
            content = content.replace('created_at: ""', f'created_at: "{now}"')
            content = content.replace('updated_at: ""', f'updated_at: "{now}"')
            note_file.write_text(content, encoding="utf-8")
        else:
            note_file.write_text(f"# {title or paper_id}\n", encoding="utf-8")
    else:
        note_file.write_text(f"# {title or paper_id}\n", encoding="utf-8")

    template_version = "v2" if template_path else None

    try:
        conn.execute(
            """INSERT INTO notes
               (note_id, paper_id, note_type, location, title, created_at, updated_at, template_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (note_id, paper_id, note_type, str(note_file), title, now, now, template_version),
        )
    except Exception:
        try:
            note_file.unlink()
        except OSError:
            pass
        raise

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
    filename: str | None = None,
) -> NoteRecord:
    """Create a note from the default template if no template_path given.

    If template_path is None, falls back to the release template under
    ``SourceCode/data``.
    """
    if template_path is None:
        template_path = Path(__file__).resolve().parents[3] / \
            "data" / "paper-note-template.md"
    return create_note(
        conn,
        paper_id,
        notes_root,
        title=title,
        template_path=template_path,
        filename=filename,
    )


def update_markdown_note_metadata(
    conn,
    paper_id: str,
    note_id: str,
    notes_root: str | Path,
    *,
    title: str | None = None,
    filename: str | None = None,
) -> NoteRecord:
    """Update Markdown note title and, when requested, safely rename its file."""
    record = _get_markdown_note_by_id(conn, paper_id, note_id)
    if record is None:
        raise ValueError(f"Markdown note {note_id!r} not found for paper {paper_id!r}.")

    current_path = Path(record.location)
    target_path = current_path
    renamed = False
    if filename is not None:
        safe_filename = safe_markdown_filename(filename, paper_id)
        target_path = _markdown_note_path(notes_root, safe_filename)
        if target_path.resolve() != current_path.resolve():
            if not current_path.exists():
                raise ValueError(f"Current Markdown note file does not exist: {current_path}")
            if target_path.exists():
                raise ValueError(f"Markdown note file already exists: {target_path}")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.rename(target_path)
            renamed = True

    new_title = record.title if title is None else title.strip()
    now = now_iso()
    try:
        conn.execute(
            "UPDATE notes SET title = ?, location = ?, updated_at = ? "
            "WHERE note_id = ? AND paper_id = ? AND note_type = 'markdown_note'",
            (new_title, str(target_path), now, note_id, paper_id),
        )
    except Exception:
        if renamed:
            try:
                target_path.rename(current_path)
            except OSError:
                pass
        raise

    return NoteRecord(
        note_id=record.note_id,
        paper_id=record.paper_id,
        note_type=record.note_type,
        location=str(target_path),
        title=new_title,
        created_at=record.created_at,
        updated_at=now,
        template_version=record.template_version,
    )
