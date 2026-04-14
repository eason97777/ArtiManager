"""Analysis — agent-powered paper analysis (Phase 8)."""

from artimanager.analysis.manager import (
    AnalysisRecord,
    create_comparison,
    create_single_analysis,
    get_analysis,
    list_analyses,
)
from artimanager.analysis.suggest import (
    suggest_follow_up_work,
    suggest_related_work,
)

__all__ = [
    "AnalysisRecord",
    "create_single_analysis",
    "create_comparison",
    "get_analysis",
    "list_analyses",
    "suggest_related_work",
    "suggest_follow_up_work",
]
