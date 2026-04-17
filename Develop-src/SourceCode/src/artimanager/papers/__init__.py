"""Paper metadata and triage state helpers."""

from artimanager.papers.manager import (
    READING_STATE_VALUES,
    RESEARCH_STATE_VALUES,
    WORKFLOW_STATUS_VALUES,
    update_paper_metadata,
    update_paper_state,
)

__all__ = [
    "WORKFLOW_STATUS_VALUES",
    "READING_STATE_VALUES",
    "RESEARCH_STATE_VALUES",
    "update_paper_state",
    "update_paper_metadata",
]
