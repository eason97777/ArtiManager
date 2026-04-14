"""FastAPI application factory for the local web workbench."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from artimanager.config import AppConfig, load_config
from artimanager.db.connection import init_db
from artimanager.web.routes.analysis import router as analysis_router
from artimanager.web.routes.dashboard import router as dashboard_router
from artimanager.web.routes.discovery import router as discovery_router
from artimanager.web.routes.papers import router as papers_router
from artimanager.web.routes.relationships import router as relationships_router
from artimanager.web.routes.search import router as search_router
from artimanager.web.routes.tracking import router as tracking_router


def _resolve_config(config: AppConfig | str | Path) -> AppConfig:
    if isinstance(config, AppConfig):
        return config
    return load_config(str(config))


def create_app(config: AppConfig | str | Path) -> FastAPI:
    """Create a configured FastAPI app."""
    cfg = _resolve_config(config)
    init_db(cfg.db_path)

    app = FastAPI(
        title="ArtiManager Local Workbench",
        docs_url=None,
        redoc_url=None,
    )
    app.state.config = cfg

    root = Path(__file__).resolve().parent
    app.state.templates = Jinja2Templates(directory=str(root / "templates"))
    app.mount("/static", StaticFiles(directory=str(root / "static")), name="static")

    app.include_router(dashboard_router)
    app.include_router(papers_router)
    app.include_router(search_router)
    app.include_router(discovery_router)
    app.include_router(tracking_router)
    app.include_router(relationships_router)
    app.include_router(analysis_router)
    return app


def create_app_from_env() -> FastAPI:
    """Factory used by uvicorn with reload mode."""
    config_path = os.environ.get("ARTIMANAGER_WEB_CONFIG")
    if not config_path:
        raise RuntimeError("ARTIMANAGER_WEB_CONFIG is not set")
    return create_app(config_path)
