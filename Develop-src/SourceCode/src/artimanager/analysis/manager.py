"""Analysis manager — create/list/get analysis records and artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artimanager.agent.factory import create_provider
from artimanager.config import AppConfig, resolve_analysis_agent_config
from artimanager.db.utils import new_id, now_iso

_PROMPT_VERSION_ANALYSIS = "phase8-analysis-v1"
_PROMPT_VERSION_COMPARE = "phase8-compare-v1"

_ANALYSIS_TYPES_WITH_MULTI_PATH = {"multi_paper_comparison"}

_SECTION_FACTS = "## Facts"
_SECTION_INFERENCE = "## Inference"


@dataclass
class AnalysisRecord:
    """Record persisted in ``analysis_records``."""

    analysis_id: str
    analysis_type: str
    paper_ids: list[str]
    prompt_version: str | None
    provider_id: str | None
    evidence_scope: str | None
    content_location: str | None
    fact_sections: dict[str, str] | None
    inference_sections: dict[str, str] | None
    created_at: str


def _parse_json_obj(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(value, dict):
        result: dict[str, str] = {}
        for k, v in value.items():
            result[str(k)] = str(v)
        return result
    return {"raw": raw}


def _row_to_record(row: tuple[Any, ...]) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=row[0],
        analysis_type=row[1],
        paper_ids=json.loads(row[2]) if row[2] else [],
        prompt_version=row[3],
        provider_id=row[4],
        evidence_scope=row[5],
        content_location=row[6],
        fact_sections=_parse_json_obj(row[7]),
        inference_sections=_parse_json_obj(row[8]),
        created_at=row[9],
    )


def _extract_sections(model_text: str) -> tuple[str, str]:
    headings = re.findall(r"(?m)^##\s+(.+?)\s*$", model_text)
    if headings != ["Facts", "Inference"]:
        raise ValueError(
            "Model output must contain exactly two top-level headings: "
            "'## Facts' then '## Inference'"
        )

    facts_match = re.search(r"(?m)^## Facts\s*$", model_text)
    inference_match = re.search(r"(?m)^## Inference\s*$", model_text)
    if facts_match is None or inference_match is None:
        raise ValueError("Model output must contain both '## Facts' and '## Inference' headings")
    if facts_match.start() > inference_match.start():
        raise ValueError("'## Facts' must appear before '## Inference'")

    facts = model_text[facts_match.end():inference_match.start()].strip()
    inference = model_text[inference_match.end():].strip()
    return facts, inference


def _fetch_paper_payload(conn, paper_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT paper_id, title, authors, year, abstract FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Paper not found: {paper_id}")

    authors = json.loads(row[2]) if row[2] else []
    fulltext_row = conn.execute(
        "SELECT full_text FROM file_assets "
        "WHERE paper_id = ? AND full_text IS NOT NULL "
        "ORDER BY LENGTH(full_text) DESC LIMIT 1",
        (paper_id,),
    ).fetchone()
    full_text = fulltext_row[0] if fulltext_row else None

    return {
        "paper_id": row[0],
        "title": row[1] or "",
        "authors": authors,
        "year": row[3],
        "abstract": row[4] or "",
        "full_text": full_text,
    }


def _build_analysis_prompt(user_prompt: str | None) -> str:
    base = (
        "Return exactly two top-level sections in Markdown:\n"
        "## Facts\n"
        "- grounded only in the provided paper\n\n"
        "## Inference\n"
        "- interpretation, relevance, limitations, or open questions\n"
        "Do not add other top-level headings."
    )
    if user_prompt:
        return f"{base}\n\nFocus: {user_prompt}"
    return base


def _build_compare_prompt(user_prompt: str | None) -> str:
    base = (
        "Compare the provided papers.\n"
        "Return exactly two top-level sections in Markdown:\n"
        "## Facts\n"
        "- evidence-grounded cross-paper observations only\n\n"
        "## Inference\n"
        "- interpretation, tradeoffs, and open questions\n"
        "Do not add other top-level headings."
    )
    if user_prompt:
        return f"{base}\n\nFocus: {user_prompt}"
    return base


def _artifact_path(cfg: AppConfig, analysis_type: str, paper_ids: list[str], analysis_id: str) -> Path:
    root = Path(cfg.notes_root)
    if analysis_type in _ANALYSIS_TYPES_WITH_MULTI_PATH:
        return root / "analysis" / "multi" / f"{analysis_id}.md"
    anchor = paper_ids[0] if paper_ids else "unknown"
    return root / "analysis" / anchor / f"{analysis_id}.md"


def create_analysis_record(
    conn,
    cfg: AppConfig,
    *,
    analysis_type: str,
    paper_ids: list[str],
    provider_id: str,
    prompt_version: str,
    evidence_scope: str,
    facts: str,
    inference: str,
    source_papers: list[dict[str, Any]],
    appendix_sections: list[tuple[str, str]] | None = None,
) -> AnalysisRecord:
    """Persist an analysis record and write its Markdown artifact."""
    analysis_id = new_id()
    created_at = now_iso()

    path = _artifact_path(cfg, analysis_type, paper_ids, analysis_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    frontmatter = [
        "---",
        f'analysis_id: "{analysis_id}"',
        f'analysis_type: "{analysis_type}"',
        f"paper_ids: {json.dumps(paper_ids, ensure_ascii=False)}",
        f'provider_id: "{provider_id}"',
        f'prompt_version: "{prompt_version}"',
        f'created_at: "{created_at}"',
        "---",
        "",
    ]

    body_lines = ["## Source Papers"]
    for paper in source_papers:
        body_lines.append(f"- {paper['paper_id']}: {paper['title'] or '(untitled)'}")
    body_lines.extend(
        [
            "",
            _SECTION_FACTS,
            facts.strip(),
            "",
            _SECTION_INFERENCE,
            inference.strip(),
        ]
    )

    if appendix_sections:
        for heading, content in appendix_sections:
            body_lines.extend(["", heading, content.strip()])

    artifact_text = "\n".join(frontmatter + body_lines) + "\n"
    path.write_text(artifact_text)

    fact_sections = json.dumps({"Facts": facts.strip()}, ensure_ascii=False)
    inference_sections = json.dumps({"Inference": inference.strip()}, ensure_ascii=False)

    conn.execute(
        """INSERT INTO analysis_records
           (analysis_id, analysis_type, paper_ids, prompt_version, provider_id,
            evidence_scope, content_location, fact_sections, inference_sections, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            analysis_id,
            analysis_type,
            json.dumps(paper_ids, ensure_ascii=False),
            prompt_version,
            provider_id,
            evidence_scope,
            str(path),
            fact_sections,
            inference_sections,
            created_at,
        ),
    )

    return AnalysisRecord(
        analysis_id=analysis_id,
        analysis_type=analysis_type,
        paper_ids=list(paper_ids),
        prompt_version=prompt_version,
        provider_id=provider_id,
        evidence_scope=evidence_scope,
        content_location=str(path),
        fact_sections={"Facts": facts.strip()},
        inference_sections={"Inference": inference.strip()},
        created_at=created_at,
    )


def create_single_analysis(
    conn,
    cfg: AppConfig,
    paper_id: str,
    *,
    prompt: str | None = None,
) -> AnalysisRecord:
    paper = _fetch_paper_payload(conn, paper_id)
    agent_cfg = resolve_analysis_agent_config(cfg)
    provider = create_provider(agent_cfg, app_config=cfg)

    model_text = provider.analyze(paper, _build_analysis_prompt(prompt))
    facts, inference = _extract_sections(model_text)

    return create_analysis_record(
        conn,
        cfg,
        analysis_type="single_paper_summary",
        paper_ids=[paper_id],
        provider_id=provider.provider_id,
        prompt_version=_PROMPT_VERSION_ANALYSIS,
        evidence_scope="single_paper",
        facts=facts,
        inference=inference,
        source_papers=[paper],
    )


def create_comparison(
    conn,
    cfg: AppConfig,
    paper_ids: list[str],
    *,
    prompt: str | None = None,
) -> AnalysisRecord:
    if len(paper_ids) < 2 or len(paper_ids) > 5:
        raise ValueError("analysis-compare requires between 2 and 5 paper IDs")

    papers = [_fetch_paper_payload(conn, pid) for pid in paper_ids]
    agent_cfg = resolve_analysis_agent_config(cfg)
    provider = create_provider(agent_cfg, app_config=cfg)

    model_text = provider.compare(papers, _build_compare_prompt(prompt))
    facts, inference = _extract_sections(model_text)

    return create_analysis_record(
        conn,
        cfg,
        analysis_type="multi_paper_comparison",
        paper_ids=list(paper_ids),
        provider_id=provider.provider_id,
        prompt_version=_PROMPT_VERSION_COMPARE,
        evidence_scope="bounded_paper_set",
        facts=facts,
        inference=inference,
        source_papers=papers,
    )


def get_analysis(conn, analysis_id: str) -> AnalysisRecord | None:
    row = conn.execute(
        "SELECT analysis_id, analysis_type, paper_ids, prompt_version, provider_id, "
        "evidence_scope, content_location, fact_sections, inference_sections, created_at "
        "FROM analysis_records WHERE analysis_id = ?",
        (analysis_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_analyses(
    conn,
    *,
    paper_id: str | None = None,
    analysis_type: str | None = None,
    limit: int = 50,
) -> list[AnalysisRecord]:
    clauses: list[str] = []
    params: list[Any] = []

    if analysis_type:
        clauses.append("analysis_type = ?")
        params.append(analysis_type)
    if paper_id:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(analysis_records.paper_ids) WHERE value = ?)"
        )
        params.append(paper_id)

    sql = (
        "SELECT analysis_id, analysis_type, paper_ids, prompt_version, provider_id, "
        "evidence_scope, content_location, fact_sections, inference_sections, created_at "
        "FROM analysis_records"
    )
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(r) for r in rows]
