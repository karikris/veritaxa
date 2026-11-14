import copy

import pytest

from tools.common import AdminError
from tools.provisional_geotags import distance_km, location_isolation, provisional_tag
from tools.publish_geotags import merge_labels


def payload(evidence=None, anchors=None):
    return {
        "evidence": evidence or [],
        "temporal_reference_evidence": anchors or [],
        "primary_group": "photo_text",
        "content_sha256": "synthetic",
    }


def evidence(place, source="description", capture=False):
    return {
        "source": source,
        "kind": "description_place_mention",
        "capture_locality_candidate": capture,
        "candidates": [place],
        "evidence_id": "synthetic",
        "excerpt": "Synthetic locality",
    }


def test_ambiguous_matches_are_preserved_without_becoming_verified():
    a = {
        "name": "Synthetic A",
        "latitude": 10,
        "longitude": 10,
        "level": "settlement",
        "geoname_id": "1",
    }
    b = {**a, "name": "Synthetic B", "latitude": -20, "geoname_id": "2"}
    p = payload([evidence(a), evidence(b)])
    original = copy.deepcopy(p)
    tag = provisional_tag(p, lambda x: x)
    assert tag["status"] == "provisional" and tag["coordinate_uncertainty_m"] is None
    assert tag["candidate_count"] == 2 and len(tag["alternatives"]) == 1
    assert "widely_separated_candidates" in tag["flags"]
    assert p == original


def test_profile_and_range_places_cannot_supply_geotags():
    p = {"latitude": 10, "longitude": 20, "name": "Synthetic"}
    assert (
        provisional_tag(payload([dict(evidence(p), source="owner_profile")]), lambda x: x)["status"]
        == "unresolved"
    )
    assert (
        provisional_tag(payload([dict(evidence(p), kind="distribution_place")]), lambda x: x)[
            "status"
        ]
        == "unresolved"
    )


def test_temporal_proxy_is_explicit_and_does_not_claim_a_travel_radius():
    tag = provisional_tag(
        payload(
            anchors=[
                {
                    "anchor_latitude": 1,
                    "anchor_longitude": 2,
                    "minutes_anchor_before_target": 12,
                    "anchor_flickr_photo_id": "synthetic-reference",
                }
            ]
        ),
        lambda x: x,
    )
    assert tag["method"] == "nearby_photo_proxy" and tag["coordinate_uncertainty_m"] is None
    assert tag["anchor_photo_id"] == "synthetic-reference"


def test_spherical_distances_handle_date_line_and_isolation():
    assert distance_km((0, 179.9), (0, -179.9)) == pytest.approx(22.239, rel=0.001)
    points = [{"latitude": 0, "longitude": 0.1}]
    location_isolation(points, [(0, 0), (0, 1), (0, 2)], k=1)
    assert points[0]["isolation_km"] == pytest.approx(11.1, abs=0.1)


def test_geotag_merge_preserves_original_labels_and_reviewed_geotags():
    row = {
        "id": "synthetic",
        "source_provider": "synthetic",
        "source_record_id": "1",
        "source_labels": {"human_label": "saved"},
    }
    plan = {
        "item_id": "synthetic",
        "source_provider": "synthetic",
        "source_record_id": "1",
        "geotag": {"status": "provisional"},
    }
    merged = merge_labels(row, plan)
    assert merged["human_label"] == "saved" and row["source_labels"] == {"human_label": "saved"}
    row["source_labels"]["_veritaxa_geotag"] = {"status": "verified"}
    with pytest.raises(AdminError):
        merge_labels(row, plan)
