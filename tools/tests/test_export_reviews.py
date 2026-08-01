from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from tools.export_reviews import (
    CONSENSUS_EXPORT_COLUMNS,
    EXPORT_COLUMNS,
    EXPORT_QUERY,
    add_derived_mappings,
    build_consensus_export,
    write_export,
)


def export_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "campaign_code": "SYNTH-2026-001",
                "target_scientific_name": "Papilio exemplaris",
                "batch_code": "SYNTH-001",
                "image_id": "synthetic-0001",
                "source_provider": "synthetic",
                "source_record_id": "record-1",
                "image_url": "https://images.example.invalid/1.jpg",
                "display_url": "https://images.example.invalid/1-small.jpg",
                "flickr_search_term": "synthetic hidden term",
                "flickrKeyword": None,
                "scientificName": "Papilio exemplaris",
                "source_labels": json.dumps({"label": "synthetic"}),
                "pipeline_metadata": json.dumps({"score": 0.5}),
                "human_label": "target_scientific_name",
                "comment": "Synthetic note",
                "reviewer_uuid": "10000000-0000-0000-0000-000000000001",
                "identifiedBy": "Synthetic reviewer",
                "reviewed_at": "2026-07-26T00:00:00+00:00",
                "schema_version": "veritaxa-review-label-v3",
                "client_version": "veritaxa-web/0.1.0",
            }
        ]
    )


def test_canonical_export_columns_preserve_granular_label_and_metadata() -> None:
    frame = export_frame()

    assert frame.columns == EXPORT_COLUMNS
    assert frame["human_label"].to_list() == ["target_scientific_name"]
    assert frame["scientificName"].to_list() == ["Papilio exemplaris"]
    assert frame["identifiedBy"].to_list() == ["Synthetic reviewer"]
    assert json.loads(frame["source_labels"][0]) == {"label": "synthetic"}
    assert json.loads(frame["pipeline_metadata"][0]) == {"score": 0.5}
    assert "review.updated_at as reviewed_at" in EXPORT_QUERY


def test_derived_export_adds_groups_without_replacing_human_label() -> None:
    frame = add_derived_mappings(export_frame())

    assert frame["human_label"].to_list() == ["target_scientific_name"]
    assert frame["matches_flickr_keyword"].to_list() == [False]
    assert frame["matches_target_scientific_name"].to_list() == [True]
    assert frame["is_insecta_positive"].to_list() == [False]
    assert frame["is_butterfly_positive"].to_list() == [False]
    assert frame["excluded_from_automatic_training"].to_list() == [False]


def test_writes_csv_and_parquet(tmp_path: Path) -> None:
    frame = export_frame()
    csv_path = tmp_path / "reviews.csv"
    parquet_path = tmp_path / "reviews.parquet"

    write_export(frame, csv_path)
    write_export(frame, parquet_path)

    assert pl.read_csv(csv_path)["human_label"].to_list() == ["target_scientific_name"]
    assert pl.read_parquet(parquet_path)["source_labels"].to_list() == ['{"label": "synthetic"}']


def test_consensus_export_handles_unanimous_plurality_ties_and_single_reviews() -> None:
    base = export_frame().to_dicts()[0]
    votes = [
        _vote(base, "unanimous", "moth", "reviewer-1", "2026-07-26T00:00:00+00:00"),
        _vote(base, "unanimous", "moth", "reviewer-2", "2026-07-27T00:00:00+00:00"),
        _vote(base, "plurality", "adult_butterfly", "reviewer-1", "2026-07-26T00:00:00+00:00"),
        _vote(base, "plurality", "adult_butterfly", "reviewer-2", "2026-07-27T00:00:00+00:00"),
        _vote(base, "plurality", "plant", "reviewer-3", "2026-07-28T00:00:00+00:00"),
        _vote(base, "tied", "plant", "reviewer-1", "2026-07-26T00:00:00+00:00"),
        _vote(base, "tied", "bird", "reviewer-2", "2026-07-29T00:00:00+00:00"),
        _vote(base, "single", "uncertain", "reviewer-1", "2026-07-30T00:00:00+00:00"),
    ]

    consensus = build_consensus_export(pl.DataFrame(votes))

    assert consensus.columns == CONSENSUS_EXPORT_COLUMNS
    by_image = {row["image_id"]: row for row in consensus.to_dicts()}
    assert by_image["unanimous"]["human_label"] == "moth"
    assert by_image["unanimous"]["review_count"] == 2
    assert by_image["unanimous"]["reviews_unanimous"] is True
    assert by_image["unanimous"]["consensus_tied"] is False
    assert by_image["plurality"]["human_label"] == "adult_butterfly"
    assert by_image["plurality"]["review_count"] == 3
    assert by_image["plurality"]["reviews_unanimous"] is False
    assert by_image["plurality"]["consensus_tied"] is False
    assert by_image["tied"]["human_label"] == "bird"
    assert by_image["tied"]["consensus_tied"] is True
    assert by_image["tied"]["reviews_unanimous"] is False
    assert by_image["single"]["human_label"] == "uncertain"
    assert by_image["single"]["review_count"] == 1
    assert by_image["single"]["reviews_unanimous"] is True
    assert by_image["single"]["consensus_tied"] is False
    assert "comment" not in consensus.columns
    assert "reviewer_uuid" not in consensus.columns
    assert "identifiedBy" not in consensus.columns


def test_consensus_uses_the_most_recent_correction_time() -> None:
    base = export_frame().to_dicts()[0]
    votes = [
        _vote(base, "corrected", "adult_butterfly", "reviewer-1", "2026-07-31T10:00:00+00:00"),
        _vote(base, "corrected", "adult_butterfly", "reviewer-2", "2026-07-30T10:00:00+00:00"),
    ]

    consensus = build_consensus_export(pl.DataFrame(votes))

    assert consensus["human_label"].to_list() == ["adult_butterfly"]
    assert consensus["reviewed_at"].to_list() == ["2026-07-31T10:00:00+00:00"]
    assert consensus["review_count"].to_list() == [2]


def _vote(
    base: dict[str, object],
    image_id: str,
    label: str,
    reviewer: str,
    reviewed_at: str,
) -> dict[str, object]:
    return {
        **base,
        "image_id": image_id,
        "human_label": label,
        "reviewer_uuid": reviewer,
        "identifiedBy": reviewer,
        "comment": f"{reviewer} comment",
        "reviewed_at": reviewed_at,
        "client_version": "veritaxa-web/0.2.0",
    }
