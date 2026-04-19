"""Tests for discovery.openalex_api."""

from __future__ import annotations

import pytest
import responses

from artimanager.discovery.openalex_api import (
    get_works_by_author,
    normalize_openalex_author_id,
)

_OPENALEX_BASE = "https://api.openalex.org"


def _work_json() -> dict:
    return {
        "id": "https://openalex.org/W123",
        "display_name": "OpenAlex Work",
        "publication_year": 2025,
        "doi": "https://doi.org/10.1234/work",
        "ids": {
            "openalex": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1234/work",
            "arxiv": "https://arxiv.org/abs/2501.00001v2",
        },
        "authorships": [
            {"author": {"display_name": "Alice Smith"}},
            {"author": {"display_name": "Bob Jones"}},
        ],
        "abstract_inverted_index": {
            "Graph": [0],
            "learning": [1],
        },
        "cited_by_count": 12,
        "primary_location": {
            "source": {
                "display_name": "Journal",
            }
        },
    }


def test_normalize_openalex_author_id_accepts_key_and_url() -> None:
    assert normalize_openalex_author_id("A123456789") == "https://openalex.org/A123456789"
    assert (
        normalize_openalex_author_id("https://openalex.org/A123456789/")
        == "https://openalex.org/A123456789"
    )


@pytest.mark.parametrize("raw", ["Alice Smith", "", "https://openalex.org/W123", "A12B"])
def test_normalize_openalex_author_id_rejects_raw_or_non_author_ids(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_openalex_author_id(raw)


@responses.activate
def test_get_works_by_author_maps_openalex_work_to_external_paper() -> None:
    responses.add(
        responses.GET,
        f"{_OPENALEX_BASE}/works",
        json={"results": [_work_json()]},
        status=200,
    )

    results = get_works_by_author("A123456789", limit=250)

    assert len(results) == 1
    paper = results[0]
    assert paper.source == "openalex"
    assert paper.external_id == "https://openalex.org/W123"
    assert paper.doi == "10.1234/work"
    assert paper.arxiv_id == "2501.00001v2"
    assert paper.title == "OpenAlex Work"
    assert paper.authors == ["Alice Smith", "Bob Jones"]
    assert paper.abstract == "Graph learning"
    request = responses.calls[0].request
    assert "filter=authorships.author.id%3Ahttps%3A%2F%2Fopenalex.org%2FA123456789" in request.url
    assert "per-page=100" in request.url
