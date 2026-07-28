from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from tools.common import AdminError, database_url, optional_https_url, validate_https_url

REQUIRED_COLUMNS = {"image_id", "image_url", "source_provider"}
KNOWN_COLUMNS = {
    *REQUIRED_COLUMNS,
    "display_url",
    "source_record_id",
    "source_page_url",
    "flickr_search_term",
    "source_labels",
    "flickr_labels_json",
    "pipeline_metadata",
}
MAX_BATCH_SIZE = 1000


@dataclass(frozen=True)
class Candidate:
    image_id: str
    image_url: str
    display_url: str | None
    source_provider: str
    source_record_id: str | None
    source_page_url: str | None
    flickr_search_term: str | None
    source_labels: Any
    pipeline_metadata: dict[str, Any] | None


@dataclass(frozen=True)
class CandidateBatch:
    code: str
    position: int
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class ImportPlan:
    campaign_code: str
    internal_name: str
    reviewer_name: str
    target_taxon_key: str | None
    target_scientific_name: str
    source_provider: str | None
    status: str
    batches: tuple[CandidateBatch, ...]

    @property
    def item_count(self) -> int:
        return sum(len(batch.candidates) for batch in self.batches)


def read_candidate_frame(path: Path) -> pl.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pl.read_parquet(path)
    if suffix == ".csv":
        return pl.read_csv(path)
    if suffix in {".ndjson", ".jsonl"}:
        return pl.read_ndjson(path)
    raise AdminError("Input must use .parquet, .csv, .ndjson, or .jsonl.")


def build_import_plan(
    frame: pl.DataFrame,
    *,
    campaign_code: str,
    internal_name: str,
    reviewer_name: str,
    batch_prefix: str,
    target_scientific_name: str,
    batch_size: int = MAX_BATCH_SIZE,
    status: str = "draft",
    target_taxon_key: str | None = None,
    source_provider: str | None = None,
    shuffle_seed: int | None = None,
) -> ImportPlan:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise AdminError(f"Input is missing required columns: {', '.join(sorted(missing))}.")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise AdminError("Batch size must be between 1 and 1000.")
    if status not in {"draft", "open"}:
        raise AdminError("Imported campaigns must be draft or open.")

    ordered = frame.sample(fraction=1.0, shuffle=True, seed=shuffle_seed) if shuffle_seed else frame
    candidates = [_candidate_from_row(row) for row in ordered.iter_rows(named=True)]
    batches: list[CandidateBatch] = []
    for offset in range(0, len(candidates), batch_size):
        batch_candidates = tuple(candidates[offset : offset + batch_size])
        image_ids = [candidate.image_id for candidate in batch_candidates]
        if len(image_ids) != len(set(image_ids)):
            raise AdminError("Duplicate image IDs are not allowed within a batch.")
        position = len(batches) + 1
        code = f"{_required_text(batch_prefix, 'batch prefix', 60)}-{position:03d}"
        batches.append(CandidateBatch(code=code, position=position, candidates=batch_candidates))

    return ImportPlan(
        campaign_code=_required_text(campaign_code, "campaign code", 80),
        internal_name=_required_text(internal_name, "internal name", 500),
        reviewer_name=_required_text(reviewer_name, "reviewer name", 120),
        target_taxon_key=_optional_text(target_taxon_key, 200),
        target_scientific_name=_required_text(
            target_scientific_name, "target scientific name", 500
        ),
        source_provider=_optional_text(source_provider, 120),
        status=status,
        batches=tuple(batches),
    )


def import_plan(
    plan: ImportPlan,
    dsn: str,
    connect: Callable[[str], Connection[Any]] = psycopg.connect,
) -> tuple[int, int, int]:
    with connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into public.review_campaigns (
                  internal_name, reviewer_name, campaign_code, target_taxon_key,
                  target_scientific_name, source_provider, status
                )
                values (%s, %s, %s, %s, %s, %s, %s::public.campaign_status)
                returning id
                """,
                (
                    plan.internal_name,
                    plan.reviewer_name,
                    plan.campaign_code,
                    plan.target_taxon_key,
                    plan.target_scientific_name,
                    plan.source_provider,
                    plan.status,
                ),
            )
            campaign_row = cursor.fetchone()
            if campaign_row is None:
                raise AdminError("Campaign insert did not return an ID.")
            campaign_id = campaign_row[0]

            for batch in plan.batches:
                cursor.execute(
                    """
                    insert into public.review_batches (
                      campaign_id, batch_code, reviewer_name, position, status, opened_at
                    )
                    values (
                      %s, %s, %s, %s, %s::public.batch_status,
                      case when %s = 'open' then now() else null end
                    )
                    returning id
                    """,
                    (
                        campaign_id,
                        batch.code,
                        f"Batch {batch.code}",
                        batch.position,
                        plan.status,
                        plan.status,
                    ),
                )
                batch_row = cursor.fetchone()
                if batch_row is None:
                    raise AdminError("Batch insert did not return an ID.")
                batch_id = batch_row[0]
                cursor.executemany(
                    """
                    insert into public.review_items (
                      batch_id, position, image_id, source_provider, source_record_id,
                      display_url, image_url, source_page_url, flickr_search_term,
                      source_labels, pipeline_metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            batch_id,
                            position,
                            candidate.image_id,
                            candidate.source_provider,
                            candidate.source_record_id,
                            candidate.display_url,
                            candidate.image_url,
                            candidate.source_page_url,
                            candidate.flickr_search_term,
                            Jsonb(candidate.source_labels)
                            if candidate.source_labels is not None
                            else None,
                            Jsonb(candidate.pipeline_metadata)
                            if candidate.pipeline_metadata is not None
                            else None,
                        )
                        for position, candidate in enumerate(batch.candidates, 1)
                    ],
                )
    return (1, len(plan.batches), plan.item_count)


def _candidate_from_row(row: dict[str, Any]) -> Candidate:
    image_id = _required_text(row.get("image_id"), "image_id", 500)
    provider = _required_text(row.get("source_provider"), "source_provider", 120)
    source_labels_value = row.get("source_labels")
    if _is_missing(source_labels_value):
        source_labels_value = row.get("flickr_labels_json")
    source_labels = _json_value(source_labels_value, "source_labels")

    metadata = _json_value(row.get("pipeline_metadata"), "pipeline_metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise AdminError("pipeline_metadata must be a JSON object when provided.")
    extras = {
        key: _json_safe(value)
        for key, value in row.items()
        if key not in KNOWN_COLUMNS and not _is_missing(value)
    }
    combined_metadata = {**(metadata or {}), **extras} or None

    return Candidate(
        image_id=image_id,
        image_url=validate_https_url(row.get("image_url"), "image_url"),
        display_url=optional_https_url(_none_if_missing(row.get("display_url")), "display_url"),
        source_provider=provider,
        source_record_id=_optional_text(_none_if_missing(row.get("source_record_id")), 500),
        source_page_url=optional_https_url(
            _none_if_missing(row.get("source_page_url")), "source_page_url"
        ),
        flickr_search_term=_optional_text(_none_if_missing(row.get("flickr_search_term")), 1000),
        source_labels=source_labels,
        pipeline_metadata=combined_metadata,
    )


def _json_value(value: object, field: str) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise AdminError(f"{field} must contain valid JSON.") from error
    return _json_safe(value)


def _json_safe(value: object) -> Any:
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def _required_text(value: object, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise AdminError(f"{field} must be non-empty and no longer than {max_length} characters.")
    return value.strip()


def _optional_text(value: object, max_length: int) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > max_length:
        raise AdminError(f"Optional text values must be no longer than {max_length} characters.")
    return value.strip() or None


def _none_if_missing(value: object) -> object | None:
    return None if _is_missing(value) else value


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import candidate rows into VeriTaxa.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--campaign-code", required=True)
    parser.add_argument("--internal-name", required=True)
    parser.add_argument("--reviewer-name", required=True)
    parser.add_argument("--batch-prefix", required=True)
    parser.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE)
    parser.add_argument("--status", choices=("draft", "open"), default="draft")
    parser.add_argument("--target-taxon-key")
    parser.add_argument("--target-scientific-name", required=True)
    parser.add_argument("--source-provider")
    parser.add_argument("--shuffle-seed", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = build_import_plan(
            read_candidate_frame(args.input),
            campaign_code=args.campaign_code,
            internal_name=args.internal_name,
            reviewer_name=args.reviewer_name,
            batch_prefix=args.batch_prefix,
            batch_size=args.batch_size,
            status=args.status,
            target_taxon_key=args.target_taxon_key,
            target_scientific_name=args.target_scientific_name,
            source_provider=args.source_provider,
            shuffle_seed=args.shuffle_seed,
        )
        if args.dry_run:
            counts = (1, len(plan.batches), plan.item_count)
        else:
            counts = import_plan(plan, database_url())
    except (AdminError, OSError, pl.exceptions.PolarsError, psycopg.Error):
        print("Import failed. No candidate details or credentials were printed.")
        return 1

    prefix = "Dry run valid" if args.dry_run else "Import complete"
    print(f"{prefix}: campaigns={counts[0]} batches={counts[1]} items={counts[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
