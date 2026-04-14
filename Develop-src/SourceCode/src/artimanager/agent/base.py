"""Abstract base class for agent providers.

All agent-dependent features must call through this interface.
No feature module should import a model SDK directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentProvider(ABC):
    """Unified interface for LLM-backed operations.

    Implementations: MockProvider, ClaudeProvider, OpenAIProvider, LocalProvider.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier for this provider instance (e.g. 'claude', 'mock')."""

    @abstractmethod
    def analyze(self, paper: dict[str, Any], prompt: str) -> str:
        """Produce an analysis of a single paper.

        Parameters
        ----------
        paper:
            Dict with at minimum ``paper_id``, ``title``, ``abstract``,
            and optionally ``full_text``.
        prompt:
            User or system prompt guiding the analysis focus.

        Returns
        -------
        Structured analysis text.
        """

    @abstractmethod
    def compare(self, papers: list[dict[str, Any]], prompt: str) -> str:
        """Compare multiple papers.

        Parameters
        ----------
        papers:
            List of paper dicts (same shape as ``analyze``).
        prompt:
            Comparison instructions.

        Returns
        -------
        Structured comparison text.
        """

    @abstractmethod
    def search_query(self, topic: str) -> list[str]:
        """Convert a natural-language topic into structured search terms.

        Parameters
        ----------
        topic:
            Free-form topic or research question.

        Returns
        -------
        List of query strings suitable for Semantic Scholar / arXiv.
        """

    @abstractmethod
    def summarize(self, text: str) -> str:
        """Summarize a block of text (e.g. an abstract or full paper).

        Parameters
        ----------
        text:
            The text to summarize.

        Returns
        -------
        Summary string.
        """
