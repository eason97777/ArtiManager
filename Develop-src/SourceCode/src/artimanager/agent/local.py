"""Local model provider via an Ollama-compatible backend."""

from __future__ import annotations

from typing import Any

import requests

from artimanager.agent.base import AgentProvider
from artimanager.agent.prompts import (
    ANALYZE_SYSTEM,
    COMPARE_SYSTEM,
    SEARCH_QUERY_SYSTEM,
    SUMMARIZE_SYSTEM,
    build_text_prompt,
    format_paper_for_prompt,
    format_papers_for_prompt,
)


class LocalProvider(AgentProvider):
    """Agent provider backed by a local Ollama-compatible HTTP endpoint."""

    def __init__(
        self,
        model: str = "",
        endpoint: str = "http://localhost:11434",
        timeout_seconds: int = 60,
    ) -> None:
        self._model = model
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds

    @property
    def provider_id(self) -> str:
        return "local"

    def _call_local_backend(self, *, system: str, user_content: str) -> str:
        if not self._model:
            raise RuntimeError(
                "Local model is not configured. Set [agent].model when provider='local'."
            )
        url = self._endpoint.rstrip("/") + "/api/generate"
        payload = {
            "model": self._model,
            "prompt": build_text_prompt(system, user_content),
            "stream": False,
        }
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Local backend unavailable at {self._endpoint}: {exc}"
            ) from exc

        if not response.ok:
            try:
                data = response.json()
            except ValueError:
                data = {}
            detail = data.get("error") or response.text or f"HTTP {response.status_code}"
            raise RuntimeError(f"Local backend error: {detail}")

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Local backend returned malformed JSON response.") from exc

        text = data.get("response")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Local backend returned malformed response payload.")
        return text.strip()

    def analyze(self, paper: dict[str, Any], prompt: str) -> str:
        user_content = f"{format_paper_for_prompt(paper)}\n\nAnalysis focus: {prompt}"
        return self._call_local_backend(system=ANALYZE_SYSTEM, user_content=user_content)

    def compare(self, papers: list[dict[str, Any]], prompt: str) -> str:
        user_content = f"{format_papers_for_prompt(papers)}\n\nComparison focus: {prompt}"
        return self._call_local_backend(system=COMPARE_SYSTEM, user_content=user_content)

    def search_query(self, topic: str) -> list[str]:
        text = self._call_local_backend(
            system=SEARCH_QUERY_SYSTEM,
            user_content=f"Topic: {topic}",
        )
        return [line.strip() for line in text.splitlines() if line.strip()]

    def summarize(self, text: str) -> str:
        return self._call_local_backend(system=SUMMARIZE_SYSTEM, user_content=text)
