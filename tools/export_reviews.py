from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import polars as pl
import psycopg

from tools.common import AdminError, database_url

SCHEMA_VERSION = "veritaxa-review-label-v1"
EXPORT_COLUMNS = [
    "campaign_code",
    "batch_code",
    "image_id",
    "source_provider",
    "source_record_id",
    "image_url",
    "display_url",
    "flickr_search_term",
    "source_labels",
    "pipeline_metadata",
    "human_label",
    "comment",
    "reviewer_uuid",
    "reviewed_at",
    "schema_version",
    "client_version",
]

EXPORT_QUERY = """
select
  campaign.campaign_code,
  batch.batch_code,
  item.image_id,
  item.source_provider,
  item.source_record_id,
  item.image_url,
  item.display_url,
  item.flickr_search_term,
  item.source_labels,
  item.pipeline_metadata,
  review.label::text as human_label,
  review.comment,
  review.reviewer_id::text as reviewer_uuid,
  review.created_at as reviewed_at,
  %s as schema_version,
  review.client_version
from public.image_reviews as review
join public.review_items as item on item.id = review.item_id
join public.review_batches as batch on batch.id = item.batch_id
join public.review_campaigns as campaign on campaign.id = batch.campaign_id
where campaign.campaign_code = %s
order by batch.position, item.position, review.created_at, review.id
"""


def fetch_export_frame(dsn: str, campaign_code: str) -> pl.DataFrame:
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(EXPORT_QUERY, (SCHEMA_VERSION, campaign_code))
        rows = cursor.fetchall()
    records = []
    for row in rows:
        record = dict(zip(EXPORT_COLUMNS, row, strict=True))
        record["source_labels"] = _canonical_json(record["source_labels"])
        record["pipeline_metadata"] = _canonical_json(record["pipeline_metadata"])
        record["reviewed_at"] = str(record["reviewed_at"])
        records.append(record)
    return pl.DataFrame(records, schema={column: pl.String for column in EXPORT_COLUMNS})


def add_derived_mappings(frame: pl.DataFrame) -> pl.DataFrame:
    label = pl.col("human_label")
    return frame.with_columns(
        label.is_in(["adult_butterfly", "caterpillar", "moth", "other_insect"]).alias(
            "is_insecta_positive"
        ),
        label.is_in(["adult_butterfly", "caterpillar", "moth"]).alias("is_lepidoptera_evidence"),
        (label == "adult_butterfly").alias("is_butterfly_positive"),
        label.is_in(["moth", "other_insect", "arachnid", "other_arthropod"]).alias(
            "is_butterfly_hard_negative"
        ),
        label.is_in(["uncertain", "image_unavailable"]).alias("excluded_from_automatic_training"),
    )


def write_export(frame: pl.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".parquet":
        frame.write_parquet(output)
    elif output.suffix.lower() == ".csv":
        frame.write_csv(output)
    else:
        raise AdminError("Output must use .parquet or .csv.")


def _canonical_json(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export joined VeriTaxa reviews.")
    parser.add_argument("--campaign-code", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--derived", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        frame = fetch_export_frame(database_url(), args.campaign_code)
        if args.derived:
            frame = add_derived_mappings(frame)
        write_export(frame, args.output)
    except (AdminError, OSError, pl.exceptions.PolarsError, psycopg.Error):
        print("Export failed. No review rows or credentials were printed.")
        return 1
    print(f"Export complete: rows={frame.height} format={args.output.suffix.lower().lstrip('.')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
