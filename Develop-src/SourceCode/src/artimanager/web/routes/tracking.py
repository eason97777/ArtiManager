"""Tracking rules routes."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from artimanager.tracking.manager import (
    create_tracking_rule,
    delete_tracking_rule,
    list_tracking_rules,
    update_tracking_rule,
)
from artimanager.tracking.runner import run_tracking
from artimanager.web.deps import (
    context,
    get_app_config,
    get_templates,
    open_db,
    with_query,
)
from artimanager.web.view_models import tracking_rule_view

router = APIRouter()


def _render_tracking_page(
    request: Request,
    *,
    status_code: int = 200,
    error_message: str | None = None,
    ok_message: str | None = None,
    run_summary: str | None = None,
):
    templates = get_templates(request)
    conn = open_db(request)
    try:
        rules = [tracking_rule_view(rule) for rule in list_tracking_rules(conn)]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "tracking_rules.html",
        context(
            request,
            rules=rules,
            error_message=error_message,
            ok_message=ok_message,
            run_summary=run_summary or request.query_params.get("run_summary"),
        ),
        status_code=status_code,
    )


@router.get("/tracking", response_class=HTMLResponse)
def tracking_page(request: Request):
    return _render_tracking_page(request)


@router.post("/tracking/create", response_class=HTMLResponse)
def tracking_create_post(
    request: Request,
    name: str = Form(...),
    rule_type: str = Form(...),
    query: str = Form(...),
    schedule: str | None = Form(default=None),
    enabled: str | None = Form(default=None),
):
    cfg = get_app_config(request)
    enabled_bool = enabled not in {None, "", "0", "false", "False"}

    conn = open_db(request)
    try:
        rule = create_tracking_rule(
            conn,
            name=name,
            rule_type=rule_type,
            query=query,
            schedule=(schedule or cfg.tracking_schedule),
            enabled=enabled_bool,
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return _render_tracking_page(request, status_code=400, error_message=str(exc))
    finally:
        conn.close()

    return RedirectResponse(
        url=with_query("/tracking", [("ok", f"Tracking rule created: {rule.tracking_rule_id}")]),
        status_code=303,
    )


@router.post("/tracking/{rule_id}/update", response_class=HTMLResponse)
def tracking_update_post(
    request: Request,
    rule_id: str,
    name: str | None = Form(default=None),
    query: str | None = Form(default=None),
    schedule: str | None = Form(default=None),
    enabled: str | None = Form(default=None),
):
    enabled_bool = None
    if enabled is not None:
        enabled_bool = enabled not in {"0", "false", "False"}
    conn = open_db(request)
    try:
        updated = update_tracking_rule(
            conn,
            rule_id,
            name=name if name not in {"", None} else None,
            query=query if query not in {"", None} else None,
            schedule=schedule if schedule not in {"", None} else None,
            enabled=enabled_bool,
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        return _render_tracking_page(request, status_code=400, error_message=message)
    finally:
        conn.close()

    return RedirectResponse(
        url=with_query("/tracking", [("ok", f"Tracking rule updated: {updated.tracking_rule_id}")]),
        status_code=303,
    )


@router.post("/tracking/{rule_id}/delete", response_class=HTMLResponse)
def tracking_delete_post(
    request: Request,
    rule_id: str,
    redirect_to: str = Form(default="/tracking"),
    delete_new_discovery: str | None = Form(default=None),
):
    parsed = urlparse(redirect_to)
    redirect_path = parsed.path or "/tracking"
    if not redirect_path.startswith("/"):
        redirect_path = "/tracking"

    conn = open_db(request)
    try:
        report = delete_tracking_rule(
            conn,
            rule_id,
            delete_new_discovery=delete_new_discovery not in {None, "", "0", "false", "False"},
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        return _render_tracking_page(request, status_code=400, error_message=message)
    finally:
        conn.close()

    message = f"Tracking rule deleted: {rule_id}"
    if delete_new_discovery not in {None, "", "0", "false", "False"}:
        message += f"; deleted {report.deleted_discovery_count} new discovery candidates"
    return RedirectResponse(url=with_query(redirect_path, [("ok", message)]), status_code=303)


@router.post("/tracking/run", response_class=HTMLResponse)
def tracking_run_post(
    request: Request,
    limit: int = Form(default=20),
):
    cfg = get_app_config(request)
    conn = open_db(request)
    try:
        report = run_tracking(conn, cfg, limit=limit)
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        conn.rollback()
        return _render_tracking_page(request, status_code=400, error_message=str(exc))
    finally:
        conn.close()

    summary = (
        f"{report.rules_processed} rules, {report.new_count} new, "
        f"{report.duplicate_count} duplicate, {report.error_count} error, "
        f"{report.warning_count} warning"
    )
    return RedirectResponse(
        url=with_query("/tracking", [("ok", "Tracking run complete."), ("run_summary", summary)]),
        status_code=303,
    )


@router.post("/tracking/{rule_id}/run", response_class=HTMLResponse)
def tracking_run_one_post(
    request: Request,
    rule_id: str,
    limit: int = Form(default=20),
):
    cfg = get_app_config(request)
    conn = open_db(request)
    try:
        report = run_tracking(conn, cfg, tracking_rule_id=rule_id, limit=limit)
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        conn.rollback()
        return _render_tracking_page(request, status_code=400, error_message=str(exc))
    finally:
        conn.close()

    summary = (
        f"rule {rule_id}: {report.new_count} new, {report.duplicate_count} duplicate, "
        f"{report.error_count} error, {report.warning_count} warning"
    )
    return RedirectResponse(
        url=with_query("/tracking", [("ok", f"Tracking rule run complete: {rule_id}"), ("run_summary", summary)]),
        status_code=303,
    )
