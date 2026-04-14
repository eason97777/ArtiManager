"""Tests for zotero.client module — mock pyzotero calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from artimanager.zotero._models import ZoteroItem
from artimanager.zotero.client import ZoteroClient


def _make_zotero_mock():
    """Create a mock pyzotero.Zotero instance."""
    z = MagicMock()
    z.items.return_value = []
    z.item.return_value = None
    z.children.return_value = []
    z.tags.return_value = []
    return z


def test_get_item_returns_zotero_item() -> None:
    z_mock = _make_zotero_mock()
    z_mock.item.return_value = {
        "key": "ABC123",
        "data": {
            "itemType": "journalArticle",
            "title": "Test Paper",
            "creators": [{"firstName": "A", "lastName": "B", "creatorType": "author"}],
            "date": "2024-01-01",
            "DOI": "10.1234/test",
            "extra": "arXiv: 2401.00001",
            "abstractNote": "Abstract text.",
            "tags": [{"tag": "ml", "type": 1}],
            "collections": [],
            "dateAdded": "2024-01-01T00:00:00Z",
            "dateModified": "2024-01-02T00:00:00Z",
        },
    }

    with patch("pyzotero.zotero.Zotero", return_value=z_mock):
        client = ZoteroClient("12345", "user", "testkey")
        item = client.get_item("ABC123")

    assert item is not None
    assert isinstance(item, ZoteroItem)
    assert item.key == "ABC123"
    assert item.title == "Test Paper"
    assert item.doi == "10.1234/test"
    assert item.arxiv_id == "2401.00001"


def test_get_item_not_found() -> None:
    z_mock = _make_zotero_mock()
    z_mock.item.return_value = None

    with patch("pyzotero.zotero.Zotero", return_value=z_mock):
        client = ZoteroClient("12345", "user", "testkey")
        item = client.get_item("NONEXISTENT")

    assert item is None


def test_list_items() -> None:
    z_mock = _make_zotero_mock()
    z_mock.items.return_value = [
        {
            "key": "K1",
            "data": {
                "itemType": "journalArticle",
                "title": "Paper 1",
                "creators": [],
            },
        },
        {
            "key": "K2",
            "data": {
                "itemType": "book",
                "title": "Paper 2",
                "creators": [],
            },
        },
    ]

    with patch("pyzotero.zotero.Zotero", return_value=z_mock):
        client = ZoteroClient("12345", "user", "testkey")
        items = client.list_items(limit=10)

    assert len(items) == 2
    assert items[0].key == "K1"
    assert items[1].key == "K2"


def test_get_children() -> None:
    z_mock = _make_zotero_mock()
    z_mock.children.return_value = [
        {
            "key": "N1",
            "data": {
                "itemType": "note",
                "note": "<p>My note</p>",
                "tags": [],
            },
        },
        {
            "key": "A1",
            "data": {
                "itemType": "attachment",
                "title": "file.pdf",
                "tags": [],
            },
        },
    ]

    with patch("pyzotero.zotero.Zotero", return_value=z_mock):
        client = ZoteroClient("12345", "user", "testkey")
        children = client.get_children("ABC123")

    assert len(children) == 2
    assert children[0].item_type == "note"
    assert children[1].item_type == "attachment"


def test_get_tags() -> None:
    z_mock = _make_zotero_mock()
    z_mock.tags.return_value = ["ml", "dl", "nlp"]

    with patch("pyzotero.zotero.Zotero", return_value=z_mock):
        client = ZoteroClient("12345", "user", "testkey")
        tags = client.get_tags()

    assert tags == ["ml", "dl", "nlp"]
