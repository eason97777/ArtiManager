"""Notes — Markdown notes and validation attachments (Phase 4)."""

from artimanager.notes.manager import (
    NoteRecord,
    create_note,
    get_note,
    init_note_from_template,
    safe_markdown_filename,
    update_markdown_note_metadata,
)

__all__ = [
    "NoteRecord",
    "create_note",
    "get_note",
    "init_note_from_template",
    "safe_markdown_filename",
    "update_markdown_note_metadata",
]
