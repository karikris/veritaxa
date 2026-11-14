import copy

import pytest

from tools.location_clue_groups import build_payload, group_clues


def test_multiple_clues_retain_sources_and_choose_one_primary():
    summary = {"named_locality_candidates_json": '[{"name":"Synthetic valley"}]'}
    evidence = [
        {"source": "description", "kind": "description_place_mention"},
        {"source": "comment", "kind": "owner_comment_locality", "author_is_owner": True},
    ]
    group, tags = group_clues(summary, evidence, [], [])
    assert group == "named_capture_locality"
    assert {"description", "photo_text", "owner_comment", "named_capture_locality"} <= set(tags)


def test_coordinates_and_anchors_are_never_promoted_to_target_coordinates():
    summary = {"flickr_photo_id": "synthetic-photo", "text_coordinate_clues_json": '[{"lat":1}]'}
    anchors = [{"anchor_latitude": 1.0, "anchor_longitude": 2.0, "time_window": "within_1_hour"}]
    before = copy.deepcopy((summary, anchors))
    payload = build_payload(summary, [], [], anchors, {"source_sha256": "synthetic"})
    assert payload["primary_group"] == "coordinate_reference"
    assert payload["inferred_target_latitude"] is payload["inferred_target_longitude"] is None
    assert payload["temporal_reference_evidence"] == anchors
    assert payload["status"] == "unverified_requires_human_location_review"
    assert (summary, anchors) == before
    assert payload == build_payload(summary, [], [], anchors, {"source_sha256": "synthetic"})


def test_profile_greetings_and_range_mentions_do_not_become_capture_clues():
    with pytest.raises(ValueError, match="No non-profile"):
        group_clues(
            {},
            [
                {"source": "owner_profile", "kind": "owner_profile_place"},
                {"source": "comment", "kind": "distribution_place"},
                {"source": "comment", "kind": "greeting_or_group_place"},
            ],
            [],
            [],
        )


def test_time_only_and_comment_only_evidence_are_supported():
    assert group_clues({}, [], [{"expression": "an hour earlier"}], [])[0] == "relative_time"
    assert (
        group_clues(
            {},
            [{"source": "comment", "kind": "comment_place_mention", "author_is_owner": False}],
            [],
            [],
        )[0]
        == "other_comment"
    )


def test_evidence_for_another_photo_is_rejected():
    with pytest.raises(ValueError, match="different target"):
        build_payload(
            {"flickr_photo_id": "synthetic-a"}, [{"flickr_photo_id": "synthetic-b"}], [], [], {}
        )
