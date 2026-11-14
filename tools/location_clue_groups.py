"""Group unverified location evidence without assigning capture coordinates."""

from __future__ import annotations

import copy
import hashlib
import json

METADATA_KEY = "_veritaxa_location_clues"
GROUP_LABELS = {
    "coordinate_reference": "Coordinates mentioned in text or tags",
    "named_capture_locality": "Named capture locality candidate",
    "nearby_photo_1h": "Same-owner geotagged photo within one hour",
    "nearby_photo_24h": "Same-owner geotagged photo within 24 hours",
    "owner_comment": "Location mention in the photo owner's comment",
    "photo_text": "Location mention in title, description or tags",
    "other_comment": "Location mention in another person's comment",
    "relative_time": "Relative-time expression only",
}
EXCLUDED_KINDS = {"greeting_or_group_place", "distribution_place", "location_question"}


def parsed(value, default):
    return (
        json.loads(value)
        if isinstance(value, str) and value
        else default
        if value is None
        else value
    )


def group_clues(summary: dict, evidence: list[dict], relative: list[dict], temporal: list[dict]):
    """Return one primary group and every applicable evidence/source tag."""
    tags = set()
    if parsed(summary.get("coordinate_machine_tags_json"), None) or parsed(
        summary.get("text_coordinate_clues_json"), []
    ):
        tags.add("coordinate_reference")
    if parsed(summary.get("named_locality_candidates_json"), []):
        tags.add("named_capture_locality")
    if summary.get("geotagged_neighbors_within_1_hour") or any(
        r.get("time_window") == "within_1_hour" for r in temporal
    ):
        tags.add("nearby_photo_1h")
    if temporal:
        tags.add("nearby_photo_24h")
    for row in evidence:
        if row.get("kind") in EXCLUDED_KINDS or row.get("source") == "owner_profile":
            continue
        source = row.get("source")
        if source in {"title", "description", "tag"}:
            tags.update({"photo_text", source})
        elif source == "comment":
            tags.add("owner_comment" if row.get("author_is_owner") is True else "other_comment")
    if relative or summary.get("relative_time_clue_count"):
        tags.add("relative_time")
    ordered = [group for group in GROUP_LABELS if group in tags]
    if not ordered:
        raise ValueError("No non-profile location clue supports this image's inclusion.")
    return ordered[0], sorted(tags)


def build_payload(
    summary: dict,
    evidence: list[dict],
    relative: list[dict],
    temporal: list[dict],
    provenance: dict,
) -> dict:
    photo_id = str(summary["flickr_photo_id"])
    for record in evidence + relative + temporal:
        if "flickr_photo_id" in record and str(record["flickr_photo_id"]) != photo_id:
            raise ValueError("Evidence belongs to a different target photo.")
    primary, tags = group_clues(summary, evidence, relative, temporal)
    fields = [
        "location_clue_status",
        "capture_time",
        "capture_time_quality",
        "coordinate_machine_tags_json",
        "text_coordinate_clues_json",
        "named_locality_candidates_json",
        "location_evidence_count",
        "photo_text_location_evidence_count",
        "owner_comment_location_evidence_count",
        "third_party_comment_location_evidence_count",
        "owner_profile_location",
        "relative_time_clue_count",
        "geotagged_neighbors_within_1_hour",
        "geotagged_neighbor_before_within_1_hour",
        "geotagged_neighbor_after_within_1_hour",
        "closest_geotagged_neighbor_json",
    ]
    payload = {
        "schema": "veritaxa-location-clues-v1",
        "flickr_photo_id": str(summary["flickr_photo_id"]),
        "status": "unverified_requires_human_location_review",
        "primary_group": primary,
        "groups": tags,
        "inferred_target_latitude": None,
        "inferred_target_longitude": None,
        "summary": {field: summary.get(field) for field in fields},
        "evidence": copy.deepcopy(evidence),
        "relative_time_evidence": copy.deepcopy(relative),
        "temporal_reference_evidence": copy.deepcopy(temporal),
        "provenance": copy.deepcopy(provenance),
        "limitations": [
            "Place candidates and quoted coordinates do not establish the photo location.",
            "Anchor coordinates belong to another photo, not this target image.",
            "Profile locations describe the account holder, not the photograph.",
        ],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["content_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    return payload
