"""Shared prompt construction for agent providers."""

from __future__ import annotations

from typing import Any

FULL_TEXT_MAX_CHARS = 50_000

ANALYZE_SYSTEM = (
    "You are a research paper analyst. Given a paper's metadata and content, "
    "produce a structured analysis with sections: Summary, Key Contributions, "
    "Methodology, Limitations, Relevance. Be concise and evidence-based."
)

COMPARE_SYSTEM = (
    "You are a research paper comparator. Given multiple papers, produce a "
    "structured comparison with sections: Shared Themes, Key Differences, "
    "Methodological Comparison, Relative Strengths. Be concise and evidence-based."
)

SEARCH_QUERY_SYSTEM = (
    "You are a research librarian. Convert the user's topic description into "
    "3-5 precise search queries suitable for academic paper databases "
    "(Semantic Scholar, arXiv). Return one query per line, nothing else."
)

SUMMARIZE_SYSTEM = (
    "You are a research summarizer. Produce a concise summary (3-5 sentences) "
    "of the provided text. Focus on the main findings and contributions."
)


def format_paper_for_prompt(paper: dict[str, Any]) -> str:
    """Format one paper payload into a deterministic prompt block."""
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
        if len(full_text_str) > FULL_TEXT_MAX_CHARS:
            truncated = full_text_str[:FULL_TEXT_MAX_CHARS]
            lines.append(f"Full text: {truncated}[truncated]")
        else:
            lines.append(f"Full text: {full_text_str}")

    return "\n".join(lines)


def format_papers_for_prompt(papers: list[dict[str, Any]]) -> str:
    """Format multiple papers for compare/suggest prompts."""
    blocks: list[str] = []
    for i, paper in enumerate(papers, start=1):
        blocks.append(f"Paper {i}:\n{format_paper_for_prompt(paper)}")
    return "\n\n".join(blocks)


def build_text_prompt(system: str, user_content: str) -> str:
    """Build a single text payload for non-chat transports."""
    return f"System:\n{system}\n\nUser:\n{user_content}"
