"""Discovery — on-demand online literature discovery (Phase 3)."""

from artimanager.discovery._models import ExternalPaper
from artimanager.discovery.engine import (
    DiscoveryRecord,
    DiscoveryReport,
    run_discovery,
    store_discovery_record,
)
from artimanager.discovery.provenance import (
    DiscoverySourceContext,
    StoreDiscoveryOutcome,
    build_provenance_key,
    store_discovery_record_with_source,
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
    "DiscoverySourceContext",
    "StoreDiscoveryOutcome",
    "build_provenance_key",
    "run_discovery",
    "store_discovery_record",
    "store_discovery_record_with_source",
    "DISCOVERY_REVIEW_ACTIONS",
    "DiscoveryReviewOutcome",
    "review_discovery_result",
]
