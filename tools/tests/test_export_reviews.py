from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from tools.export_reviews import EXPORT_COLUMNS, add_derived_mappings, write_export


def export_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "campaign_code": "SYNTH-2026-001",
                "batch_code": "SYNTH-001",
                "image_id": "synthetic-0001",
                "source_provider": "synthetic",
                "source_record_id": "record-1",
                "image_url": "https://images.example.invalid/1.jpg",
                "display_url": "https://images.example.invalid/1-small.jpg",
                "flickr_search_term": "synthetic hidden term",
                "source_labels": json.dumps({"label": "synthetic"}),
                "pipeline_metadata": json.dumps({"score": 0.5}),
                "human_label": "adult_butterfly",
                "comment": "Synthetic note",
                "reviewer_uuid": "10000000-0000-0000-0000-000000000001",
                "reviewed_at": "2026-07-26T00:00:00+00:00",
                "schema_version": "veritaxa-review-label-v1",
                "client_version": "veritaxa-web/0.1.0",
            }
        ]
    )


def test_canonical_export_columns_preserve_granular_label_and_metadata() -> None:
    frame = export_frame()

    assert frame.columns == EXPORT_COLUMNS
    assert frame["human_label"].to_list() == ["adult_butterfly"]
    assert json.loads(frame["source_labels"][0]) == {"label": "synthetic"}
    assert json.loads(frame["pipeline_metadata"][0]) == {"score": 0.5}


def test_derived_export_adds_groups_without_replacing_human_label() -> None:
    frame = add_derived_mappings(export_frame())

    assert frame["human_label"].to_list() == ["adult_butterfly"]
    assert frame["is_insecta_positive"].to_list() == [True]
    assert frame["is_butterfly_positive"].to_list() == [True]
    assert frame["excluded_from_automatic_training"].to_list() == [False]


def test_writes_csv_and_parquet(tmp_path: Path) -> None:
    frame = export_frame()
    csv_path = tmp_path / "reviews.csv"
    parquet_path = tmp_path / "reviews.parquet"

    write_export(frame, csv_path)
    write_export(frame, parquet_path)

    assert pl.read_csv(csv_path)["human_label"].to_list() == ["adult_butterfly"]
    assert pl.read_parquet(parquet_path)["source_labels"].to_list() == ['{"label": "synthetic"}']
