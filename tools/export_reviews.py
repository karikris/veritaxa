from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing
from datetime import datetime
from itertools import groupby
from pathlib import Path

import polars as pl
import psycopg

from tools.common import AdminError, database_url
from tools.tabular_output import validate_output_path, write_records

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

LABEL_PRIORITY = {label: index for index, label in enumerate(EXPECTED_RESULT_PRIORITY)}
BULKY_COLUMNS = frozenset({"source_labels", "pipeline_metadata"})
DERIVED_LABELS = {
    "matches_flickr_keyword": {"flickr_keyword_match"},
    "matches_target_scientific_name": {"target_scientific_name"},
    "is_insecta_positive": {"adult_butterfly", "caterpillar", "moth", "other_insect"},
    "is_lepidoptera_evidence": {"adult_butterfly", "caterpillar", "moth"},
    "is_butterfly_positive": {"adult_butterfly"},
    "is_butterfly_hard_negative": {"moth", "other_insect", "arachnid", "other_arthropod"},
    "excluded_from_automatic_training": {"uncertain", "image_unavailable"},
}

_PROJECTIONS = dict(
    zip(
        EXPORT_COLUMNS,
        (
            "campaign.campaign_code",
            "campaign.target_scientific_name",
            "batch.batch_code",
            "item.image_id",
            "item.source_provider",
            "item.source_record_id",
            "item.image_url",
            "item.display_url",
            "item.flickr_search_term",
            'review."flickrKeyword"',
            'review."scientificName"',
            "item.source_labels",
            "item.pipeline_metadata",
            "review.label::text as human_label",
            "review.comment",
            "review.reviewer_id::text as reviewer_uuid",
            'review."identifiedBy"',
            "review.updated_at as reviewed_at",
            "%s as schema_version",
            "review.client_version",
        ),
        strict=True,
    )
)
_ITEM_JOINS = """
join public.review_batches as batch on batch.id = item.batch_id
join public.review_campaigns as campaign on campaign.id = batch.campaign_id
"""
_FILTER = "where campaign.campaign_code = %s"
_RAW_ORDER = "order by batch.position, item.position, review.created_at, review.id"
_CONSENSUS_ORDER = (
    'order by campaign.campaign_code collate "C", '
    'batch.batch_code collate "C", item.image_id collate "C"'
)
_TALLY = """
join lateral (
  select jsonb_object_agg(vote.label, vote.n) as label_counts,
         max(vote.reviewed_at) as reviewed_at
  from (
    select review.label::text as label, count(*) as n, max(review.updated_at) as reviewed_at
    from public.image_reviews as review
    where review.item_id = item.id
    group by review.label
  ) as vote
) as tally on tally.label_counts is not null
"""


def export_schema(
    *, consensus: bool = False, derived: bool = False, lean: bool = False
) -> pl.Schema:
    columns = CONSENSUS_EXPORT_COLUMNS if consensus else EXPORT_COLUMNS
    schema = pl.Schema(
        {
            column: pl.UInt32
            if column == "review_count"
            else pl.Boolean
            if column in {"reviews_unanimous", "consensus_tied"}
            else pl.String
            for column in columns
            if not lean or column not in BULKY_COLUMNS
        }
    )
    if derived:
        schema.update({column: pl.Boolean for column in DERIVED_LABELS})
    return schema


def export_query(*, consensus: bool = False, lean: bool = False) -> tuple[str, list[str]]:
    """Only trusted, fixed projections enter SQL; the campaign remains a bound parameter."""
    columns = list(export_schema(consensus=consensus, lean=lean))
    if consensus:
        columns = [
            column
            for column in columns
            if column
            not in {
                "human_label",
                "review_count",
                "reviews_unanimous",
                "consensus_tied",
            }
        ]
    expressions = [
        _PROJECTIONS[column] if not consensus or column != "reviewed_at" else "tally.reviewed_at"
        for column in columns
    ]
    if consensus:
        columns.append("label_counts")
        expressions.append("tally.label_counts")
        source = "from public.review_items as item" + _ITEM_JOINS + _TALLY
        order = _CONSENSUS_ORDER
    else:
        source = (
            "from public.image_reviews as review "
            "join public.review_items as item on item.id = review.item_id" + _ITEM_JOINS
        )
        order = _RAW_ORDER
    return "select " + ",\n  ".join(
        expressions
    ) + "\n" + source + "\n" + _FILTER + "\n" + order, columns


EXPORT_QUERY = export_query()[0]


def fetch_export_frame(dsn: str, campaign_code: str) -> pl.DataFrame:
    """Eager compatibility API for small in-memory callers; the CLI never uses it."""
    with closing(iter_export_records(dsn, campaign_code)) as records:
        return pl.DataFrame(records, schema=export_schema())


def iter_export_records(
    dsn: str,
    campaign_code: str,
    *,
    consensus: bool = False,
    derived: bool = False,
    lean: bool = False,
) -> Iterator[dict[str, object]]:
    query, columns = export_query(consensus=consensus, lean=lean)
    with psycopg.connect(dsn) as connection:
        connection.read_only = True
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with (
            connection.cursor() as cursor,
            closing(cursor.stream(query, (SCHEMA_VERSION, campaign_code), size=1)) as rows,
        ):
            # libpq single-row mode avoids both a full client result and per-row FETCH round trips.
            for row in rows:
                record = dict(zip(columns, row, strict=True))
                for column in BULKY_COLUMNS.intersection(record):
                    record[column] = _canonical_json(record[column])
                record["reviewed_at"] = str(record["reviewed_at"])
                if consensus:
                    counts = record.pop("label_counts")
                    if not isinstance(counts, dict):
                        raise AdminError("Consensus counts were not valid.")
                    record.update(summarize_votes(counts))
                if derived:
                    record.update(derived_mappings(record))
                yield record


def export_reviews(
    dsn: str,
    campaign_code: str,
    output: Path,
    *,
    consensus: bool = False,
    derived: bool = False,
    lean: bool = False,
) -> int:
    validate_output_path(output)
    with closing(
        iter_export_records(dsn, campaign_code, consensus=consensus, derived=derived, lean=lean)
    ) as records:
        return write_records(
            records, export_schema(consensus=consensus, derived=derived, lean=lean), output
        )


def summarize_votes(counts: Mapping[str, int]) -> dict[str, object]:
    if not counts or any(type(count) is not int or count <= 0 for count in counts.values()):
        raise AdminError("Consensus counts were not valid.")
    highest = max(counts.values())
    tied = [label for label, count in counts.items() if count == highest]
    return {
        "human_label": min(
            tied, key=lambda label: (LABEL_PRIORITY.get(label, len(LABEL_PRIORITY)), label)
        ),
        "review_count": sum(counts.values()),
        "reviews_unanimous": len(counts) == 1,
        "consensus_tied": len(tied) > 1,
    }


def derived_mappings(record: Mapping[str, object]) -> dict[str, object]:
    label = record["human_label"]
    result = {
        column: None if label is None else label in labels
        for column, labels in DERIVED_LABELS.items()
    }
    if record.get("consensus_tied"):
        result["excluded_from_automatic_training"] = True
    return result


def add_derived_mappings(frame: pl.DataFrame) -> pl.DataFrame:
    label = pl.col("human_label")
    expressions = [
        label.is_in(sorted(labels)).alias(column) for column, labels in DERIVED_LABELS.items()
    ]
    result = frame.with_columns(expressions)
    if "consensus_tied" in frame.columns:
        result = result.with_columns(
            (pl.col("excluded_from_automatic_training") | pl.col("consensus_tied")).alias(
                "excluded_from_automatic_training"
            )
        )
    return result


def iter_consensus_votes(records: Iterator[dict[str, object]]) -> Iterator[dict[str, object]]:
    """Reduce ordered votes while retaining one metadata record and small label counts."""
    key_columns = ("campaign_code", "batch_code", "image_id")
    summary_columns = {"human_label", "review_count", "reviews_unanimous", "consensus_tied"}
    for _key, votes in groupby(
        records, key=lambda row: tuple(row[column] for column in key_columns)
    ):
        first = next(votes)
        counts = Counter({str(first["human_label"]): 1})
        latest = str(first["reviewed_at"])
        for vote in votes:  # noqa: B031 - consume the remainder after next(), not a second traversal
            counts[str(vote["human_label"])] += 1
            timestamp = str(vote["reviewed_at"])
            if datetime.fromisoformat(timestamp) > datetime.fromisoformat(latest):
                latest = timestamp
        record = {
            column: first[column]
            for column in CONSENSUS_EXPORT_COLUMNS
            if column not in summary_columns
        }
        record["reviewed_at"] = latest
        record.update(summarize_votes(counts))
        yield record


def build_consensus_export(frame: pl.DataFrame) -> pl.DataFrame:
    """Eager compatibility wrapper; the CLI aggregates in SQL before fetching metadata."""
    ordered = frame.sort(["campaign_code", "batch_code", "image_id"], maintain_order=True)
    return pl.DataFrame(
        iter_consensus_votes(ordered.iter_rows(named=True, buffer_size=1)),
        schema=export_schema(consensus=True),
    )


def write_export(frame: pl.DataFrame, output: Path) -> None:
    write_records(frame.iter_rows(named=True), frame.schema, output)


def _canonical_json(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export joined VeriTaxa reviews.")
    parser.add_argument("--campaign-code", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--derived", action="store_true")
    parser.add_argument("--consensus", action="store_true")
    parser.add_argument(
        "--lean",
        action="store_true",
        help="Omit source_labels and pipeline_metadata; retain all other columns.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_output_path(args.output)
        count = export_reviews(
            database_url(),
            args.campaign_code,
            args.output,
            consensus=args.consensus,
            derived=args.derived,
            lean=args.lean,
        )
    except (AdminError, OSError, ValueError, pl.exceptions.PolarsError, psycopg.Error):
        print("Export failed. No review rows or credentials were printed.")
        return 1
    print(f"Export complete: rows={count} format={args.output.suffix.lower().lstrip('.')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
