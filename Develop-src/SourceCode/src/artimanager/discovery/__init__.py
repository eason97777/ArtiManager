"""Discovery — on-demand online literature discovery (Phase 3)."""

from artimanager.discovery._models import ExternalPaper
from artimanager.discovery.engine import (
    DiscoveryRecord,
    DiscoveryReport,
    run_discovery,
    store_discovery_record,
)
from artimanager.discovery.review import (
    DISCOVERY_REVIEW_ACTIONS,
    DiscoveryReviewOutcome,
    review_discovery_result,
)

__all__ = [
    "ExternalPaper",
    "DiscoveryRecord",
    "DiscoveryReport",
    "run_discovery",
    "store_discovery_record",
    "DISCOVERY_REVIEW_ACTIONS",
    "DiscoveryReviewOutcome",
    "review_discovery_result",
]
