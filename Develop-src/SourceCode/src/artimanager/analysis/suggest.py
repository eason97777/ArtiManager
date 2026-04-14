"""Analysis suggestion pipeline for related and follow-up work."""

from __future__ import annotations

import json
from typing import Any

from artimanager.agent.factory import create_provider
from artimanager.analysis.manager import AnalysisRecord, create_analysis_record
from artimanager.config import AppConfig, resolve_analysis_agent_config
from artimanager.relationships.manager import RelationshipRecord, create_relationship

_PROMPT_VERSION_SUGGEST = "phase8-suggest-v1"


def _word_tokens(title: str) -> set[str]:
    return set(title.lower().split())


def _token_overlap(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))


def _fetch_paper_payload(conn, paper_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT paper_id, title, authors, year, abstract, doi, arxiv_id FROM papers WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Paper not found: {paper_id}")

    authors = json.loads(row[2]) if row[2] else []
    fulltext_row = conn.execute(
        "SELECT full_text FROM file_assets WHERE paper_id = ? AND full_text IS NOT NULL "
        "ORDER BY LENGTH(full_text) DESC LIMIT 1",
        (paper_id,),
    ).fetchone()
    return {
        "paper_id": row[0],
        "title": row[1] or "",
        "authors": authors,
        "year": row[3],
        "abstract": row[4] or "",
        "doi": row[5],
        "arxiv_id": row[6],
        "full_text": fulltext_row[0] if fulltext_row else None,
    }


def _existing_linked_ids(conn, anchor_paper_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT source_paper_id, target_paper_id FROM relationships "
        "WHERE source_paper_id = ? OR target_paper_id = ?",
        (anchor_paper_id, anchor_paper_id),
    ).fetchall()
    linked: set[str] = set()
    for source_id, target_id in rows:
        if source_id == anchor_paper_id:
            linked.add(target_id)
        if target_id == anchor_paper_id:
            linked.add(source_id)
    return linked


def _discover_candidates(conn, anchor_paper_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT imported_paper_id FROM discovery_results "
        "WHERE trigger_type = 'paper_anchor' AND trigger_ref = ? "
        "AND status = 'imported' AND imported_paper_id IS NOT NULL "
        "ORDER BY created_at DESC",
        (anchor_paper_id,),
    ).fetchall()
    return [r[0] for r in rows if r[0]]


def _metadata_candidates(conn, anchor: dict[str, Any]) -> list[str]:
    rows = conn.execute(
        "SELECT paper_id, title, doi, arxiv_id FROM papers WHERE paper_id != ?",
        (anchor["paper_id"],),
    ).fetchall()

    anchor_tokens = _word_tokens(anchor["title"])
    anchor_doi = anchor.get("doi")
    anchor_arxiv = anchor.get("arxiv_id")

    doi_prefix = None
    if isinstance(anchor_doi, str):
        parts = anchor_doi.split("/", 2)
        if len(parts) >= 2:
            doi_prefix = parts[0]

    arxiv_prefix = anchor_arxiv[:5] if isinstance(anchor_arxiv, str) and anchor_arxiv else None

    candidates: list[str] = []
    for paper_id, title, doi, arxiv_id in rows:
        matched = False
        if doi_prefix and isinstance(doi, str):
            other_parts = doi.split("/", 2)
            if len(other_parts) >= 2 and other_parts[0] == doi_prefix:
                matched = True
        if not matched and arxiv_prefix and isinstance(arxiv_id, str):
            matched = arxiv_id[:5] == arxiv_prefix
        if not matched and title:
            matched = _token_overlap(anchor_tokens, _word_tokens(title)) > 0.6
        if matched:
            candidates.append(paper_id)
    return candidates


def _filter_candidates(
    conn,
    anchor_paper_id: str,
    *,
    discovered_ids: list[str],
    metadata_ids: list[str],
    explicit_ids: list[str],
    limit: int,
) -> list[str]:
    cap = min(max(limit, 1), 12)
    linked = _existing_linked_ids(conn, anchor_paper_id)
    seen: set[str] = set()
    ordered: list[str] = []

    for pid in discovered_ids + metadata_ids + explicit_ids:
        if not pid:
            continue
        if pid == anchor_paper_id:
            continue
        if pid in linked:
            continue
        if pid in seen:
            continue
        exists = conn.execute(
            "SELECT 1 FROM papers WHERE paper_id = ?",
            (pid,),
        ).fetchone()
        if exists is None:
            continue
        seen.add(pid)
        ordered.append(pid)
        if len(ordered) >= cap:
            break

    return ordered


def _build_prompt(mode: str, limit: int, anchor: dict[str, Any], candidate_ids: list[str]) -> str:
    relation = "prior_work" if mode == "related" else "follow_up_work"
    return (
        f"You are ranking candidate papers for {relation} suggestions.\n"
        f"Anchor paper id: {anchor['paper_id']}\n"
        f"Allowed candidate ids: {', '.join(candidate_ids)}\n"
        f"Select at most {limit} candidates.\n"
        "Output TSV only, one line per accepted suggestion:\n"
        "<paper_id>\\t<confidence 0..1>\\t<reason>\n"
        "Do not output any prose, headers, or markdown."
    )


def _parse_tsv_suggestions(
    model_text: str,
    *,
    allowed_ids: set[str],
    limit: int,
) -> tuple[list[tuple[str, float, str]], list[str]]:
    accepted: list[tuple[str, float, str]] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for raw_line in model_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            skipped.append(line)
            continue
        target_id = parts[0].strip()
        confidence_raw = parts[1].strip()
        reason = "\t".join(parts[2:]).strip()
        if target_id not in allowed_ids:
            skipped.append(line)
            continue
        if target_id in seen:
            skipped.append(line)
            continue
        try:
            confidence = float(confidence_raw)
        except ValueError:
            skipped.append(line)
            continue
        if confidence < 0.0 or confidence > 1.0:
            skipped.append(line)
            continue
        if not reason:
            skipped.append(line)
            continue
        accepted.append((target_id, confidence, reason))
        seen.add(target_id)
        if len(accepted) >= limit:
            break

    return accepted, skipped


def _suggest_mode(
    conn,
    cfg: AppConfig,
    *,
    paper_id: str,
    mode: str,
    candidate_paper_ids: list[str] | None = None,
    limit: int = 8,
) -> tuple[AnalysisRecord, list[RelationshipRecord]]:
    if mode not in {"related", "follow_up"}:
        raise ValueError(f"Unsupported suggestion mode: {mode!r}")

    requested_limit = max(limit, 1)
    anchor = _fetch_paper_payload(conn, paper_id)
    discovered_ids = _discover_candidates(conn, paper_id)
    metadata_ids = _metadata_candidates(conn, anchor)
    explicit_ids = list(candidate_paper_ids or [])
    candidate_ids = _filter_candidates(
        conn,
        paper_id,
        discovered_ids=discovered_ids,
        metadata_ids=metadata_ids,
        explicit_ids=explicit_ids,
        limit=requested_limit,
    )

    agent_cfg = resolve_analysis_agent_config(cfg)
    provider = create_provider(agent_cfg, app_config=cfg)
    source_papers = [anchor] + [_fetch_paper_payload(conn, pid) for pid in candidate_ids]

    accepted: list[tuple[str, float, str]] = []
    skipped: list[str] = []
    raw_output = ""
    if candidate_ids:
        prompt = _build_prompt(mode, requested_limit, anchor, candidate_ids)
        raw_output = provider.compare(source_papers, prompt)
        accepted, skipped = _parse_tsv_suggestions(
            raw_output,
            allowed_ids=set(candidate_ids),
            limit=requested_limit,
        )

    relationship_type = "prior_work" if mode == "related" else "follow_up_work"
    analysis_type = (
        "related_work_suggestion"
        if mode == "related"
        else "follow_up_work_suggestion"
    )

    relationships: list[RelationshipRecord] = []
    for target_id, confidence, reason in accepted:
        rec = create_relationship(
            conn,
            source_paper_id=paper_id,
            target_paper_id=target_id,
            relationship_type=relationship_type,
            evidence_type="agent_inferred",
            evidence_text=reason,
            confidence=confidence,
            created_by="analysis_pipeline",
            status="suggested",
        )
        relationships.append(rec)

    facts_lines = [
        f"Anchor paper: {paper_id}",
        f"Candidate count after filtering: {len(candidate_ids)}",
        f"Accepted suggestions: {len(accepted)}",
    ]
    if candidate_ids:
        facts_lines.append("Candidate IDs: " + ", ".join(candidate_ids))
    else:
        facts_lines.append("Candidate IDs: (none)")

    if accepted:
        inference_lines = [f"- {pid}: {reason} (confidence={confidence:.2f})" for pid, confidence, reason in accepted]
        inference = "\n".join(inference_lines)
    else:
        inference = "No relationship suggestions were accepted."

    accepted_section = (
        "\n".join([f"- {pid}\t{confidence:.2f}\t{reason}" for pid, confidence, reason in accepted])
        if accepted
        else "(none)"
    )
    skipped_section = "\n".join([f"- {line}" for line in skipped]) if skipped else "(none)"
    raw_section = raw_output.strip() if raw_output.strip() else "(empty)"

    record = create_analysis_record(
        conn,
        cfg,
        analysis_type=analysis_type,
        paper_ids=[paper_id] + candidate_ids,
        provider_id=provider.provider_id,
        prompt_version=_PROMPT_VERSION_SUGGEST,
        evidence_scope="bounded_candidates",
        facts="\n".join(facts_lines),
        inference=inference,
        source_papers=source_papers,
        appendix_sections=[
            ("## Accepted Suggestions", accepted_section),
            ("## Skipped Lines", skipped_section),
            ("## Raw Model Output", raw_section),
        ],
    )
    return record, relationships


def suggest_related_work(
    conn,
    cfg: AppConfig,
    paper_id: str,
    *,
    candidate_paper_ids: list[str] | None = None,
    limit: int = 8,
) -> tuple[AnalysisRecord, list[RelationshipRecord]]:
    return _suggest_mode(
        conn,
        cfg,
        paper_id=paper_id,
        mode="related",
        candidate_paper_ids=candidate_paper_ids,
        limit=limit,
    )


def suggest_follow_up_work(
    conn,
    cfg: AppConfig,
    paper_id: str,
    *,
    candidate_paper_ids: list[str] | None = None,
    limit: int = 8,
) -> tuple[AnalysisRecord, list[RelationshipRecord]]:
    return _suggest_mode(
        conn,
        cfg,
        paper_id=paper_id,
        mode="follow_up",
        candidate_paper_ids=candidate_paper_ids,
        limit=limit,
    )
