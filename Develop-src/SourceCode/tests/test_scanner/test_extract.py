"""Tests for scanner.extract — PDF metadata and full-text extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from artimanager.scanner.extract import (
    PaperMetadata,
    PymupdfExtractor,
    _choose_title_from_first_page,
    _extract_abstract,
    _find_arxiv_id,
    _find_doi,
    _find_year,
    is_low_quality_title,
    normalize_title_text,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
REAL_PDF = DATA_DIR / "1803.02029v1.pdf"


class TestRegexHelpers:
    """Unit tests for regex-based field extraction."""

    def test_find_doi_standard(self) -> None:
        assert _find_doi("doi: 10.1234/foo.bar") == "10.1234/foo.bar"

    def test_find_doi_none(self) -> None:
        assert _find_doi("no doi here") == ""

    def test_find_doi_strips_trailing_punct(self) -> None:
        result = _find_doi("See 10.1234/abc.def).")
        assert not result.endswith(")")
        assert not result.endswith(".")

    def test_find_arxiv_id(self) -> None:
        assert _find_arxiv_id("arXiv:1803.02029v1") == "1803.02029v1"

    def test_find_arxiv_id_case_insensitive(self) -> None:
        assert _find_arxiv_id("ARXIV: 2301.12345") == "2301.12345"

    def test_find_arxiv_id_none(self) -> None:
        assert _find_arxiv_id("nothing") == ""

    def test_find_year_valid(self) -> None:
        assert _find_year("Published in 2018") == 2018

    def test_find_year_prefers_academic_range(self) -> None:
        assert _find_year("1234 and 2021 and 9999") == 2021

    def test_find_year_none(self) -> None:
        assert _find_year("no year") is None


class TestTitleQuality:
    """Title normalization and fallback heuristics."""

    def test_normalize_title_text_preserves_unicode(self) -> None:
        assert normalize_title_text("  量子   Control\nPaper  ") == "量子 Control Paper"

    @pytest.mark.parametrize(
        "title",
        [
            "",
            "  ",
            "þÿBad title",
            "A\ufffdB\ufffdC",
            "cid:12 cid:34",
            "!!! --- ???",
            "x",
            "/tmp/paper.pdf",
            "paper.pdf",
        ],
    )
    def test_low_quality_title_detected(self, title: str) -> None:
        assert is_low_quality_title(title)

    def test_plausible_title_not_low_quality(self) -> None:
        assert not is_low_quality_title("A Robust Method for Local Paper Management")

    def test_first_page_title_skips_abstract_heading(self) -> None:
        text = "\n\nAbstract\nA Robust Method for Local Paper Management\nAuthors"
        assert _choose_title_from_first_page(text) == "A Robust Method for Local Paper Management"


class TestExtractAbstract:
    """Heuristic abstract extraction."""

    def test_finds_abstract_section(self) -> None:
        text = "Title\n\nAbstract\nThis paper presents a novel approach to the problem of X and Y.\n\nINTRODUCTION\nBlah"
        result = _extract_abstract(text)
        assert "novel approach" in result

    def test_empty_input(self) -> None:
        assert _extract_abstract("") == ""

    def test_no_abstract_marker(self) -> None:
        assert _extract_abstract("Just some random text without markers") == ""


@pytest.mark.skipif(not REAL_PDF.exists(), reason="test PDF not available")
class TestPymupdfExtractorRealPdf:
    """Integration tests using the real arXiv PDF."""

    def test_extract_metadata_returns_paper_metadata(self) -> None:
        ext = PymupdfExtractor()
        meta = ext.extract_metadata(REAL_PDF)
        assert isinstance(meta, PaperMetadata)

    def test_title_not_empty(self) -> None:
        ext = PymupdfExtractor()
        meta = ext.extract_metadata(REAL_PDF)
        assert meta.title

    def test_year_detected(self) -> None:
        ext = PymupdfExtractor()
        meta = ext.extract_metadata(REAL_PDF)
        assert meta.year is not None
        assert 1950 <= meta.year <= 2030

    def test_arxiv_id_detected(self) -> None:
        ext = PymupdfExtractor()
        meta = ext.extract_metadata(REAL_PDF)
        assert "1803.02029" in meta.arxiv_id

    def test_full_text_not_empty(self) -> None:
        ext = PymupdfExtractor()
        text = ext.extract_full_text(REAL_PDF)
        assert text is not None
        assert len(text) > 100

    def test_full_text_contains_content(self) -> None:
        ext = PymupdfExtractor()
        text = ext.extract_full_text(REAL_PDF)
        assert text is not None
        # The paper should contain some recognisable words
        lower = text.lower()
        assert "abstract" in lower or "introduction" in lower
