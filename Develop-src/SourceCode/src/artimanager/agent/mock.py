"""Mock agent provider for testing.

Returns deterministic canned responses so tests never need real API calls.
"""

from __future__ import annotations

from typing import Any

from artimanager.agent.base import AgentProvider


class MockProvider(AgentProvider):
    """Agent provider that returns configurable fixed responses.

    Parameters
    ----------
    responses:
        Optional dict mapping method names to return values.
        Missing keys fall back to built-in defaults.
    """

    _DEFAULTS = {
        "analyze": "[Mock analysis] This paper presents a method and evaluates it.",
        "compare": "[Mock comparison] The selected papers differ in approach and scope.",
        "search_query": ["mock query term 1", "mock query term 2"],
        "summarize": "[Mock summary] The text describes a research contribution.",
    }

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self._responses: dict[str, Any] = {**self._DEFAULTS}
        if responses:
            self._responses.update(responses)
        self._call_log: list[tuple[str, tuple, dict]] = []

    @property
    def provider_id(self) -> str:
        return "mock"

    @property
    def call_log(self) -> list[tuple[str, tuple, dict]]:
        """Inspect calls made to this provider (useful in tests)."""
        return list(self._call_log)

    def _record(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self._call_log.append((method, args, kwargs))
        return self._responses[method]

    def analyze(self, paper: dict[str, Any], prompt: str) -> str:
        return self._record("analyze", paper, prompt)

    def compare(self, papers: list[dict[str, Any]], prompt: str) -> str:
        return self._record("compare", papers, prompt)

    def search_query(self, topic: str) -> list[str]:
        return self._record("search_query", topic)

    def summarize(self, text: str) -> str:
        return self._record("summarize", text)
