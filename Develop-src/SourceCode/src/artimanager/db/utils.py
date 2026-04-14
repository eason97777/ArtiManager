"""Shared database utilities."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """Return a new UUID4 string."""
    return str(uuid.uuid4())
