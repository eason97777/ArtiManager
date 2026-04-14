"""Claude agent provider backed by the Anthropic SDK."""

from __future__ import annotations

import importlib
import logging
from typing import Any

from artimanager.agent.base import AgentProvider

logger = logging.getLogger(__name__)

_FULL_TEXT_MAX_CHARS = 50_000

_ANALYZE_SYSTEM = (
    "You are a research paper analyst. Given a paper's metadata and content, "
    "produce a structured analysis with sections: Summary, Key Contributions, "
    "Methodology, Limitations, Relevance. Be concise and evidence-based."
)

_COMPARE_SYSTEM = (
    "You are a research paper comparator. Given multiple papers, produce a "
    "structured comparison with sections: Shared Themes, Key Differences, "
    "Methodological Comparison, Relative Strengths. Be concise and evidence-based."
)

_SEARCH_QUERY_SYSTEM = (
    "You are a research librarian. Convert the user's topic description into "
    "3-5 precise search queries suitable for academic paper databases "
    "(Semantic Scholar, arXiv). Return one query per line, nothing else."
)

_SUMMARIZE_SYSTEM = (
    "You are a research summarizer. Produce a concise summary (3-5 sentences) "
    "of the provided text. Focus on the main findings and contributions."
)


class ClaudeProvider(AgentProvider):
    """Agent provider backed by the Anthropic Claude API.

    Parameters
    ----------
    model:
        Model identifier, e.g. ``"claude-sonnet-4-20250514"``.
    api_key:
        Anthropic API key.  Should be read from an environment variable
        via the configuration layer — never hard-coded.
    """

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str = "") -> None:
        self._model = model
        self._api_key = api_key
        self._anthropic: Any = None
        self._client: Any = None

    @property
    def provider_id(self) -> str:
        return "claude"

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            anthropic = importlib.import_module("anthropic")
            self._anthropic = anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK is not installed. "
                "Install it with: pip install anthropic"
            ) from exc

    @staticmethod
    def _extract_text(message: Any) -> str:
        content = getattr(message, "content", None)
        if not content:
            return ""

        chunks: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                chunks.append(str(text).strip())
        return "\n".join([c for c in chunks if c]).strip()

    @staticmethod
    def _format_paper_for_prompt(paper: dict[str, Any]) -> str:
        title = str(paper.get("title") or "")
        raw_authors = paper.get("authors") or []
        if isinstance(raw_authors, list):
            authors = ", ".join(str(a) for a in raw_authors if a)
        else:
            authors = str(raw_authors)
        year = paper.get("year")
        abstract = str(paper.get("abstract") or "")

        lines = [
            f"Title: {title}",
            f"Authors: {authors}",
            f"Year: {year if year is not None else ''}",
            f"Abstract: {abstract}",
        ]

        full_text = paper.get("full_text")
        if full_text:
            full_text_str = str(full_text)
            if len(full_text_str) > _FULL_TEXT_MAX_CHARS:
                truncated = full_text_str[:_FULL_TEXT_MAX_CHARS]
                lines.append(f"Full text: {truncated}[truncated]")
            else:
                lines.append(f"Full text: {full_text_str}")

        return "\n".join(lines)

    @classmethod
    def _format_papers_for_prompt(cls, papers: list[dict[str, Any]]) -> str:
        blocks: list[str] = []
        for i, paper in enumerate(papers, start=1):
            blocks.append(f"Paper {i}:\n{cls._format_paper_for_prompt(paper)}")
        return "\n\n".join(blocks)

    def _call_model(self, *, system: str, user_content: str, max_tokens: int = 2048) -> str:
        self._ensure_client()
        anthropic = self._anthropic
        if anthropic is None:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            return self._extract_text(message)
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
        except anthropic.AuthenticationError as exc:
            logger.error("Anthropic authentication failed: %s", exc)
            raise RuntimeError("Invalid API key") from exc
        except anthropic.APIError as exc:
            logger.error("Anthropic API error: %s", exc)
            raise RuntimeError(f"Anthropic API error: {exc}") from exc

        return self._extract_text(message)

    def analyze(self, paper: dict[str, Any], prompt: str) -> str:
        user_content = f"{self._format_paper_for_prompt(paper)}\n\nAnalysis focus: {prompt}"
        return self._call_model(system=_ANALYZE_SYSTEM, user_content=user_content)

    def compare(self, papers: list[dict[str, Any]], prompt: str) -> str:
        user_content = f"{self._format_papers_for_prompt(papers)}\n\nComparison focus: {prompt}"
        return self._call_model(system=_COMPARE_SYSTEM, user_content=user_content)

    def search_query(self, topic: str) -> list[str]:
        text = self._call_model(system=_SEARCH_QUERY_SYSTEM, user_content=f"Topic: {topic}")
        return [line.strip() for line in text.splitlines() if line.strip()]

    def summarize(self, text: str) -> str:
        return self._call_model(system=_SUMMARIZE_SYSTEM, user_content=text)
