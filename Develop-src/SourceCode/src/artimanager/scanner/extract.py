"""PDF metadata and full-text extraction.

Provides a ``TextExtractor`` protocol for future OCR extensibility
and a default ``PymupdfExtractor`` implementation using pymupdf (fitz).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PaperMetadata:
    """Metadata extracted from a PDF."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str = ""
    arxiv_id: str = ""
    abstract: str = ""


# ---------------------------------------------------------------------------
# Extractor protocol (OCR hook for future phases)
# ---------------------------------------------------------------------------

@runtime_checkable
class TextExtractor(Protocol):
    """Interface for text extraction backends."""

    def extract_metadata(self, pdf_path: str | Path) -> PaperMetadata: ...

    def extract_full_text(self, pdf_path: str | Path) -> str | None: ...


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"\b(10\.\d{4,}/[^\s]+)")
_ARXIV_RE = re.compile(r"(?:arXiv:?\s*)(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


def _find_doi(text: str) -> str:
    m = _DOI_RE.search(text)
    return m.group(1).rstrip(".,;)") if m else ""


def _find_arxiv_id(text: str) -> str:
    m = _ARXIV_RE.search(text)
    return m.group(1) if m else ""


def _find_year(text: str) -> int | None:
    matches = _YEAR_RE.findall(text)
    # prefer years in a reasonable academic range
    for y in matches:
        val = int(y)
        if 1950 <= val <= 2030:
            return val
    return None


# ---------------------------------------------------------------------------
# pymupdf implementation
# ---------------------------------------------------------------------------

class PymupdfExtractor:
    """Extract metadata and full text from PDFs using pymupdf (fitz)."""

    def extract_metadata(self, pdf_path: str | Path) -> PaperMetadata:
        """Extract metadata from PDF document info and first-page text.

        Best-effort: missing fields are returned as empty / None.
        """
        import fitz  # pymupdf

        pdf_path = Path(pdf_path)
        meta = PaperMetadata()

        try:
            doc = fitz.open(str(pdf_path))
        except Exception:
            return meta

        try:
            # --- PDF document-level metadata ---
            info = doc.metadata or {}
            meta.title = (info.get("title") or "").strip()
            raw_author = (info.get("author") or "").strip()
            if raw_author:
                # authors often separated by , or ; or "and"
                meta.authors = [
                    a.strip()
                    for a in re.split(r"[;,]|\band\b", raw_author)
                    if a.strip()
                ]

            # --- First-page text for richer signals ---
            first_page_text = ""
            if len(doc) > 0:
                first_page_text = doc[0].get_text() or ""

            # Title fallback: first non-empty line of first page
            if not meta.title and first_page_text:
                for line in first_page_text.split("\n"):
                    stripped = line.strip()
                    if stripped and len(stripped) > 5:
                        meta.title = stripped
                        break

            combined = first_page_text
            # DOI
            meta.doi = _find_doi(combined)
            # arXiv ID
            meta.arxiv_id = _find_arxiv_id(combined)
            # Year
            if info.get("creationDate"):
                meta.year = _find_year(info["creationDate"])
            if meta.year is None:
                meta.year = _find_year(combined)

            # --- Abstract heuristic ---
            meta.abstract = _extract_abstract(first_page_text)

        finally:
            doc.close()

        return meta

    def extract_full_text(self, pdf_path: str | Path) -> str | None:
        """Extract all text from a PDF.

        Returns ``None`` for encrypted or image-only PDFs that yield no text.
        """
        import fitz

        pdf_path = Path(pdf_path)
        try:
            doc = fitz.open(str(pdf_path))
        except Exception:
            return None

        try:
            pages: list[str] = []
            for page in doc:
                text = page.get_text()
                if text:
                    pages.append(text)
            doc.close()

            if not pages:
                return None
            return "\n\n".join(pages)
        except Exception:
            doc.close()
            return None


def _extract_abstract(first_page_text: str) -> str:
    """Best-effort abstract extraction from first-page text.

    Looks for an "Abstract" heading and takes text until the next
    section heading or a reasonable length cutoff.
    """
    if not first_page_text:
        return ""

    # Try to find explicit "Abstract" marker
    pattern = re.compile(
        r"(?:^|\n)\s*(?:ABSTRACT|Abstract)\s*[:\-—]?\s*\n?(.*?)(?:\n\s*(?:[A-Z][A-Z ]{3,}|1\s|I\.\s|Introduction|INTRODUCTION)|\Z)",
        re.DOTALL,
    )
    m = pattern.search(first_page_text)
    if m:
        abstract = m.group(1).strip()
        # collapse whitespace
        abstract = re.sub(r"\s+", " ", abstract)
        if len(abstract) > 50:
            return abstract[:3000]  # cap length

    return ""
