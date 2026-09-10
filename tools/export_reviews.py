from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import polars as pl
import psycopg

from tools.common import AdminError, database_url
from tools.tabular_output import write_records

SCHEMA_VERSION = "veritaxa-review-label-v3"
EXPORT_COLUMNS = [
    "campaign_code",
    "target_scientific_name",
    "batch_code",
    "image_id",
    "source_provider",
    "source_record_id",
    "image_url",
    "display_url",
    "flickr_search_term",
    "flickrKeyword",
    "scientificName",
    "source_labels",
    "pipeline_metadata",
    "human_label",
    "comment",
    "reviewer_uuid",
    "identifiedBy",
    "reviewed_at",
    "schema_version",
    "client_version",
]

CONSENSUS_EXPORT_COLUMNS = [
    "campaign_code",
    "target_scientific_name",
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
    "review_count",
    "reviews_unanimous",
    "consensus_tied",
    "reviewed_at",
    "schema_version",
]

EXPECTED_RESULT_PRIORITY = (
    "target_scientific_name",
    "adult_butterfly",
    "caterpillar",
    "moth",
    "other_insect",
    "arachnid",
    "other_arthropod",
    "mammal_or_person",
    "bird",
    "other_animal",
    "plant",
    "fungus",
    "artifact_or_illustration",
    "no_biological_subject",
    "uncertain",
    "image_unavailable",
    "flickr_keyword_match",
)

EXPORT_QUERY = """
select
  campaign.campaign_code,
  campaign.target_scientific_name,
  batch.batch_code,
  item.image_id,
  item.source_provider,
  item.source_record_id,
  item.image_url,
  item.display_url,
  item.flickr_search_term,
  review."flickrKeyword",
  review."scientificName",
  item.source_labels,
  item.pipeline_metadata,
  review.label::text as human_label,
  review.comment,
  review.reviewer_id::text as reviewer_uuid,
  review."identifiedBy",
  review.updated_at as reviewed_at,
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
        (label == "flickr_keyword_match").alias("matches_flickr_keyword"),
        (label == "target_scientific_name").alias("matches_target_scientific_name"),
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


def build_consensus_export(frame: pl.DataFrame) -> pl.DataFrame:
    grouped: dict[tuple[object, object, object], list[dict[str, object]]] = {}
    for record in frame.to_dicts():
        key = (record["campaign_code"], record["batch_code"], record["image_id"])
        grouped.setdefault(key, []).append(record)

    priority = {label: index for index, label in enumerate(EXPECTED_RESULT_PRIORITY)}
    records: list[dict[str, object]] = []
    for votes in grouped.values():
        first = votes[0]
        counts = Counter(str(vote["human_label"]) for vote in votes)
        highest_count = max(counts.values())
        tied_labels = [label for label, count in counts.items() if count == highest_count]
        winner = min(tied_labels, key=lambda label: (priority.get(label, len(priority)), label))
        records.append(
            {
                "campaign_code": first["campaign_code"],
                "target_scientific_name": first["target_scientific_name"],
                "batch_code": first["batch_code"],
                "image_id": first["image_id"],
                "source_provider": first["source_provider"],
                "source_record_id": first["source_record_id"],
                "image_url": first["image_url"],
                "display_url": first["display_url"],
                "flickr_search_term": first["flickr_search_term"],
                "source_labels": first["source_labels"],
                "pipeline_metadata": first["pipeline_metadata"],
                "human_label": winner,
                "review_count": len(votes),
                "reviews_unanimous": len(counts) == 1,
                "consensus_tied": len(tied_labels) > 1,
                "reviewed_at": _latest_reviewed_at(votes),
                "schema_version": first["schema_version"],
            }
        )

    records.sort(
        key=lambda record: (
            str(record["campaign_code"]),
            str(record["batch_code"]),
            str(record["image_id"]),
        )
    )
    schema = {
        column: (
            pl.UInt32
            if column == "review_count"
            else pl.Boolean
            if column in {"reviews_unanimous", "consensus_tied"}
            else pl.String
        )
        for column in CONSENSUS_EXPORT_COLUMNS
    }
    return pl.DataFrame(records, schema=schema)


def write_export(frame: pl.DataFrame, output: Path) -> None:
    write_records(frame.iter_rows(named=True), frame.schema, output)


def _canonical_json(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _latest_reviewed_at(votes: list[dict[str, object]]) -> str:
    timestamps = [str(vote["reviewed_at"]) for vote in votes]
    return max(timestamps, key=datetime.fromisoformat)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export joined VeriTaxa reviews.")
    parser.add_argument("--campaign-code", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--derived", action="store_true")
    parser.add_argument("--consensus", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        frame = fetch_export_frame(database_url(), args.campaign_code)
        if args.consensus:
            frame = build_consensus_export(frame)
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
