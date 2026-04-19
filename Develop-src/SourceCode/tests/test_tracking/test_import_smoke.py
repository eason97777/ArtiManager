"""Clean import smoke tests for tracking modules."""

from __future__ import annotations

import subprocess
import sys


def _run_import_smoke(code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_import_tracking_package_clean_process() -> None:
    _run_import_smoke("import artimanager.tracking")


def test_import_tracking_manager_clean_process() -> None:
    _run_import_smoke("from artimanager.tracking.manager import create_tracking_rule; print('ok')")


def test_import_tracking_runner_clean_process() -> None:
    _run_import_smoke("import artimanager.tracking.runner; print('ok')")
