"""Shared web-layer helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates

from artimanager.config import AppConfig
from artimanager.db.connection import get_connection


def get_app_config(request: Request) -> AppConfig:
    return request.app.state.config  # type: ignore[no-any-return]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


def open_db(request: Request):
    cfg = get_app_config(request)
    return get_connection(cfg.db_path)


def parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def parse_csv(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    values = [v.strip() for v in raw.split(",") if v.strip()]
    return values or None


def context(request: Request, **extra):
    payload = {
        "request": request,
        "ok_message": request.query_params.get("ok"),
        "error_message": request.query_params.get("error"),
    }
    payload.update(extra)
    return payload


def with_query(path: str, params: Iterable[tuple[str, str | int | None]]) -> str:
    cleaned: list[tuple[str, str | int]] = []
    for key, value in params:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        cleaned.append((key, value))
    if not cleaned:
        return path
    return f"{path}?{urlencode(cleaned)}"
