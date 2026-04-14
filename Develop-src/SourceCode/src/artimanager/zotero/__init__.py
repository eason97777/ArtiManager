"""Zotero — bibliography integration (Phase 5)."""

from artimanager.zotero._models import ZoteroItem, item_from_zotero_data
from artimanager.zotero.client import ZoteroClient
from artimanager.zotero.linker import (
    ZoteroLink,
    find_paper_by_zotero_key,
    get_zotero_link,
    link_paper_to_zotero,
    read_zotero_notes,
    sync_paper_metadata,
)

__all__ = [
    "ZoteroClient",
    "ZoteroItem",
    "ZoteroLink",
    "item_from_zotero_data",
    "link_paper_to_zotero",
    "get_zotero_link",
    "find_paper_by_zotero_key",
    "sync_paper_metadata",
    "read_zotero_notes",
]
