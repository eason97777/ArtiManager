"""File discovery — scan local folders for PDF candidates.

Safety contract: this module never moves, renames, or deletes files.
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileCandidate:
    """A file discovered during a folder scan."""

    absolute_path: str
    filename: str
    filesize: int
    sha256: str
    mime_type: str


def _sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_folder(folder_path: str | Path) -> list[FileCandidate]:
    """Recursively scan *folder_path* for PDF files.

    Parameters
    ----------
    folder_path:
        Root directory to scan.

    Returns
    -------
    List of ``FileCandidate`` objects, one per PDF found.
    Non-PDF files are silently skipped.
    """
    root = Path(folder_path)
    if not root.is_dir():
        raise FileNotFoundError(f"Scan target is not a directory: {root}")

    candidates: list[FileCandidate] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".pdf":
            continue

        mime, _ = mimetypes.guess_type(str(p))
        candidates.append(
            FileCandidate(
                absolute_path=str(p.resolve()),
                filename=p.name,
                filesize=p.stat().st_size,
                sha256=_sha256(p),
                mime_type=mime or "application/pdf",
            )
        )
    return candidates
