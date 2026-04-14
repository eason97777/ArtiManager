"""Release packaging and documentation checks."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_exposes_artimanager_script() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["artimanager"] == "artimanager.cli.main:cli"


def test_docs_use_artimanager_as_primary_command() -> None:
    for rel_path in ("README.md", "docs/user-guide.md"):
        text = (ROOT / rel_path).read_text()
        assert "python -m artimanager.cli.main" not in text
        assert "artimanager scan --config config.toml" in text
