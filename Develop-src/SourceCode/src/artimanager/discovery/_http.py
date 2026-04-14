"""HTTP utility with retry, timeout, and rate limiting.

All API adapters in the discovery layer should use this module
so that network behaviour is consistent and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_SECONDS = (1, 2, 4)
_RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class HttpJsonResult:
    """JSON response metadata for adapters that need status-aware fallbacks."""

    status_code: int | None
    payload: Any = None
    error: str | None = None


def http_get(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
    rate_limit: float = 0.1,
    headers: dict[str, str] | None = None,
) -> dict | None:
    """Perform a GET request with exponential backoff retry.

    Parameters
    ----------
    url:
        Target URL.
    params:
        Query parameters.
    timeout:
        Request timeout in seconds.
    rate_limit:
        Seconds to sleep after a successful request.  Set to 0 in tests.

    Returns
    -------
    Parsed JSON dict on success, ``None`` on failure (after all retries).
    """
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers=headers)
            resp.raise_for_status()
            if rate_limit > 0:
                time.sleep(rate_limit)
            return resp.json()
        except requests.RequestException as exc:
            logger.warning(
                "HTTP GET %s failed (attempt %d/%d): %s",
                url, attempt + 1, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
            else:
                return None
    return None


def http_get_raw(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
    rate_limit: float = 0.1,
    headers: dict[str, str] | None = None,
) -> str | None:
    """Perform a GET request and return raw text (for XML/non-JSON APIs).

    Same retry/backoff behaviour as ``http_get`` but returns the raw
    response body instead of parsing JSON.
    """
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers=headers)
            resp.raise_for_status()
            if rate_limit > 0:
                time.sleep(rate_limit)
            return resp.text
        except requests.RequestException as exc:
            logger.warning(
                "HTTP GET %s failed (attempt %d/%d): %s",
                url, attempt + 1, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
            else:
                return None
    return None


def http_post(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
    rate_limit: float = 0.1,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict | None:
    """Perform a POST request with exponential backoff retry.

    Parameters are aligned with ``http_get``; this helper is intended for
    adapters that need non-GET request methods while keeping shared retry and
    timeout behavior.
    """
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.post(
                url,
                params=params,
                json=json_body,
                timeout=timeout,
                headers=headers,
            )
            resp.raise_for_status()
            if rate_limit > 0:
                time.sleep(rate_limit)
            return resp.json()
        except requests.RequestException as exc:
            logger.warning(
                "HTTP POST %s failed (attempt %d/%d): %s",
                url, attempt + 1, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
            else:
                return None
    return None


def _request_json_result(
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
    rate_limit: float = 0.1,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> HttpJsonResult:
    method_upper = method.upper()
    if method_upper not in {"GET", "POST"}:
        raise ValueError(f"Unsupported HTTP method: {method}")

    for attempt in range(_MAX_RETRIES):
        try:
            if method_upper == "GET":
                resp = requests.get(
                    url,
                    params=params,
                    timeout=timeout,
                    headers=headers,
                )
            else:
                resp = requests.post(
                    url,
                    params=params,
                    json=json_body,
                    timeout=timeout,
                    headers=headers,
                )
            status_code = resp.status_code
            resp.raise_for_status()
            if rate_limit > 0:
                time.sleep(rate_limit)
            try:
                return HttpJsonResult(status_code=status_code, payload=resp.json())
            except ValueError as exc:
                logger.warning("HTTP %s %s returned invalid JSON: %s", method_upper, url, exc)
                return HttpJsonResult(
                    status_code=status_code,
                    error="invalid JSON response",
                )
        except requests.HTTPError as exc:
            response = exc.response
            status_code = response.status_code if response is not None else None
            logger.warning(
                "HTTP %s %s failed (attempt %d/%d): %s",
                method_upper,
                url,
                attempt + 1,
                _MAX_RETRIES,
                exc,
            )
            should_retry = status_code is None or status_code in _RETRY_STATUS_CODES
            if should_retry and attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
            else:
                return HttpJsonResult(status_code=status_code, error=str(exc))
        except requests.RequestException as exc:
            logger.warning(
                "HTTP %s %s failed (attempt %d/%d): %s",
                method_upper,
                url,
                attempt + 1,
                _MAX_RETRIES,
                exc,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
            else:
                return HttpJsonResult(status_code=None, error=str(exc))
    return HttpJsonResult(status_code=None, error="request failed")


def http_get_json_result(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
    rate_limit: float = 0.1,
    headers: dict[str, str] | None = None,
) -> HttpJsonResult:
    """Perform a GET request and preserve final HTTP status metadata."""
    return _request_json_result(
        "GET",
        url,
        params=params,
        timeout=timeout,
        rate_limit=rate_limit,
        headers=headers,
    )


def http_post_json_result(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
    rate_limit: float = 0.1,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> HttpJsonResult:
    """Perform a POST request and preserve final HTTP status metadata."""
    return _request_json_result(
        "POST",
        url,
        params=params,
        timeout=timeout,
        rate_limit=rate_limit,
        headers=headers,
        json_body=json_body,
    )
