"""Search — indexing and retrieval (Phase 2)."""

from artimanager.search.indexer import IndexReport, index_paper, rebuild_search_index
from artimanager.search.query import SearchFilters, SearchResult, search_all, search_fulltext, search_notes, search_papers

__all__ = [
    "IndexReport",
    "SearchFilters",
    "SearchResult",
    "index_paper",
    "rebuild_search_index",
    "search_all",
    "search_fulltext",
    "search_notes",
    "search_papers",
]
