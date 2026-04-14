"""Tests for zotero._models module."""

from __future__ import annotations

from artimanager.zotero._models import (
    ZoteroItem,
    _parse_extra,
    item_from_zotero_data,
)


class TestParseExtra:
    def test_arxiv_id_extracted(self) -> None:
        assert _parse_extra("arXiv: 2301.12345") == "2301.12345"

    def test_arxiv_id_with_prefix(self) -> None:
        assert _parse_extra("arXiv:1908.03456\nPMID: 12345") == "1908.03456"

    def test_arxiv_id_case_insensitive(self) -> None:
        assert _parse_extra("arxiv: 2103.00001") == "2103.00001"

    def test_no_arxiv_id(self) -> None:
        assert _parse_extra("PMID: 12345\nISSN: 1234-5678") is None

    def test_none_extra(self) -> None:
        assert _parse_extra(None) is None

    def test_empty_extra(self) -> None:
        assert _parse_extra("") is None


class TestZoteroItem:
    def test_defaults(self) -> None:
        item = ZoteroItem(key="ABC", item_type="journalArticle", title="Test", creators=[])
        assert item.tags == []
        assert item.collections == []
        assert item.doi is None
        assert item.arxiv_id is None

    def test_from_zotero_data(self) -> None:
        raw = {
            "key": "ABC123",
            "itemType": "journalArticle",
            "title": "Deep Learning",
            "creators": [
                {"firstName": "Yann", "lastName": "LeCun", "creatorType": "author"},
            ],
            "date": "2015-06-01",
            "DOI": "10.1234/dl",
            "extra": "arXiv: 1501.00001",
            "abstractNote": "A review of deep learning.",
            "tags": [{"tag": "deep-learning", "type": 1}],
            "url": "https://example.com",
            "collections": ["COL1"],
            "dateAdded": "2024-01-01T00:00:00Z",
            "dateModified": "2024-02-01T00:00:00Z",
        }
        item = item_from_zotero_data(raw)
        assert item.key == "ABC123"
        assert item.item_type == "journalArticle"
        assert item.title == "Deep Learning"
        assert item.doi == "10.1234/dl"
        assert item.arxiv_id == "1501.00001"
        assert item.abstract == "A review of deep learning."
        assert item.tags == ["deep-learning"]
        assert item.url == "https://example.com"
        assert item.collections == ["COL1"]

    def test_creators_as_name_dict(self) -> None:
        raw = {
            "key": "X",
            "itemType": "book",
            "title": "A Book",
            "creators": [{"name": "Org Name", "creatorType": "author"}],
        }
        item = item_from_zotero_data(raw)
        assert len(item.creators) == 1

    def test_no_doi_no_arxiv(self) -> None:
        raw = {
            "key": "Y",
            "itemType": "conferencePaper",
            "title": "No IDs",
            "creators": [],
        }
        item = item_from_zotero_data(raw)
        assert item.doi is None
        assert item.arxiv_id is None
