"""Zotero API client — thin wrapper around pyzotero."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from artimanager.zotero._models import ZoteroItem, item_from_zotero_data

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pyzotero import zotero as pyzotero_module


class ZoteroClient:
    """Thin wrapper around pyzotero that returns normalised ZoteroItem objects."""

    def __init__(
        self,
        library_id: str,
        library_type: str = "user",
        api_key: str | None = None,
    ) -> None:
        try:
            from pyzotero import zotero as _zotero
        except ImportError:
            raise ImportError(
                "pyzotero is required for Zotero integration. "
                "Install it with: pip install pyzotero"
            )

        self._zotero: pyzotero_module.Zotero = _zotero.Zotero(
            library_id, library_type, api_key
        )
        self.library_id = library_id
        self.library_type = library_type

    def get_item(self, item_key: str) -> ZoteroItem | None:
        """Fetch a single item by its Zotero key."""
        try:
            result = self._zotero.item(item_key)
            if result is None:
                return None
            # pyzotero returns {"key": "...", "data": {...}, ...}
            data = result.get("data", {}) if isinstance(result, dict) else {}
            data = {"key": result.get("key", item_key), **data}
            return item_from_zotero_data(data)
        except Exception:
            logger.exception("Failed to fetch Zotero item %s", item_key)
            return None

    def list_items(
        self,
        item_type: str | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[ZoteroItem]:
        """List items, optionally filtered by type or tag."""
        kwargs: dict = {"limit": limit}
        if item_type:
            kwargs["itemType"] = item_type
        if tag:
            kwargs["tag"] = tag

        try:
            items = self._zotero.items(**kwargs)
            return [
                item_from_zotero_data({"key": item["key"], **item.get("data", item)})
                for item in items
            ]
        except Exception:
            logger.exception("Failed to list Zotero items")
            return []

    def get_children(self, item_key: str) -> list[ZoteroItem]:
        """Get child items (attachments, notes) of a parent item."""
        try:
            children = self._zotero.children(item_key)
            return [
                item_from_zotero_data({"key": child["key"], **child.get("data", child)})
                for child in children
            ]
        except Exception:
            logger.exception("Failed to fetch children of Zotero item %s", item_key)
            return []

    def get_tags(self) -> list[str]:
        """List all tags in the library."""
        try:
            return self._zotero.tags()
        except Exception:
            logger.exception("Failed to fetch Zotero tags")
            return []

    def get_children_raw(self, item_key: str) -> list[dict]:
        """Get child items as raw dicts (for note HTML access)."""
        try:
            return self._zotero.children(item_key)
        except Exception:
            logger.exception("Failed to fetch raw children of Zotero item %s", item_key)
            return []
