"""Tests for scanner.scan — file discovery."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from artimanager.scanner.scan import FileCandidate, scan_folder

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
REAL_PDF = DATA_DIR / "1803.02029v1.pdf"


class TestScanFolder:
    """scan_folder() behaviour."""

    def test_finds_pdf_in_flat_dir(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake content")
        result = scan_folder(tmp_path)
        assert len(result) == 1
        assert result[0].filename == "paper.pdf"

    def test_finds_pdf_recursively(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "nested.pdf").write_bytes(b"%PDF-1.4 nested")
        result = scan_folder(tmp_path)
        assert len(result) == 1
        assert result[0].filename == "nested.pdf"

    def test_ignores_non_pdf(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        result = scan_folder(tmp_path)
        assert result == []

    def test_empty_dir(self, tmp_path: Path) -> None:
        result = scan_folder(tmp_path)
        assert result == []

    def test_raises_on_missing_dir(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            scan_folder(tmp_path / "nonexistent")

    def test_sha256_is_consistent(self, tmp_path: Path) -> None:
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4 deterministic")
        r1 = scan_folder(tmp_path)
        r2 = scan_folder(tmp_path)
        assert r1[0].sha256 == r2[0].sha256

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 AAA")
        (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 BBB")
        result = scan_folder(tmp_path)
        assert result[0].sha256 != result[1].sha256


class TestFileCandidate:
    """FileCandidate dataclass properties."""

    def test_frozen(self, tmp_path: Path) -> None:
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4 frozen")
        c = scan_folder(tmp_path)[0]
        with pytest.raises(AttributeError):
            c.filename = "changed"  # type: ignore[misc]

    def test_fields_populated(self, tmp_path: Path) -> None:
        pdf = tmp_path / "test.pdf"
        content = b"%PDF-1.4 some content here"
        pdf.write_bytes(content)
        c = scan_folder(tmp_path)[0]
        assert c.absolute_path == str(pdf.resolve())
        assert c.filename == "test.pdf"
        assert c.filesize == len(content)
        assert len(c.sha256) == 64
        assert c.mime_type == "application/pdf"


@pytest.mark.skipif(not REAL_PDF.exists(), reason="test PDF not available")
class TestScanRealPdf:
    """Integration tests using the real arXiv PDF."""

    def test_scan_finds_real_pdf(self, tmp_path: Path) -> None:
        dest = tmp_path / "1803.02029v1.pdf"
        shutil.copy2(REAL_PDF, dest)
        result = scan_folder(tmp_path)
        assert len(result) == 1
        assert result[0].filename == "1803.02029v1.pdf"
        assert result[0].filesize > 0
        assert len(result[0].sha256) == 64
