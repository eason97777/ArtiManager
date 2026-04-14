"""Relationships — paper relationship engine (Phase 6)."""

from artimanager.relationships.manager import (
    RelationshipRecord,
    create_relationship,
    delete_relationship,
    get_relationship,
    get_relationships,
    list_relationships,
    update_relationship_status,
)
from artimanager.relationships.suggest import suggest_relationships

__all__ = [
    "RelationshipRecord",
    "create_relationship",
    "delete_relationship",
    "get_relationship",
    "get_relationships",
    "list_relationships",
    "suggest_relationships",
    "update_relationship_status",
]
