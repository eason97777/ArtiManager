"""Tests for discovery._models."""

from artimanager.discovery._models import ExternalPaper


class TestExternalPaper:
    def test_defaults(self) -> None:
        p = ExternalPaper()
        assert p.title == ""
        assert p.authors == []
        assert p.year is None
        assert p.source == ""
        assert p.external_id == ""

    def test_with_values(self) -> None:
        p = ExternalPaper(
            title="Test Paper",
            authors=["Alice", "Bob"],
            year=2023,
            doi="10.1234/test",
            source="semantic_scholar",
            external_id="10.1234/test",
        )
        assert p.title == "Test Paper"
        assert len(p.authors) == 2
        assert p.doi == "10.1234/test"
        assert p.source == "semantic_scholar"
