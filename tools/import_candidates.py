from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import polars as pl
import psycopg

from tools.candidate_input import iter_candidate_rows
from tools.candidate_rows import REQUIRED_COLUMNS, Candidate, candidate_from_row
from tools.candidate_spool import SHUFFLE_ALGORITHM, CandidateChunk, validate_candidates
from tools.common import AdminError, database_url
from tools.import_publish import ImportSpec, import_spec, publish_candidates

MAX_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class CandidateBatch:
    code: str
    position: int
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True, slots=True)
class ImportPlan(ImportSpec):
    """Eager compatibility plan for small callers, never used by the CLI."""

    batches: tuple[CandidateBatch, ...]

    @property
    def item_count(self) -> int:
        return sum(len(batch.candidates) for batch in self.batches)


def read_candidate_frame(path: Path) -> pl.DataFrame:
    """Original eager reader retained for small compatibility/equivalence tests."""
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
    spec = import_spec(
        campaign_code=campaign_code,
        internal_name=internal_name,
        reviewer_name=reviewer_name,
        batch_prefix=batch_prefix,
        target_scientific_name=target_scientific_name,
        batch_size=batch_size,
        status=status,
        target_taxon_key=target_taxon_key,
        source_provider=source_provider,
    )
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise AdminError(f"Input is missing required columns: {', '.join(sorted(missing))}.")
    # Preserve legacy Polars order in this explicit compatibility API; fix seed 0.
    ordered = (
        frame.sample(fraction=1.0, shuffle=True, seed=shuffle_seed)
        if shuffle_seed is not None
        else frame
    )
    candidates = [candidate_from_row(row) for row in ordered.iter_rows(named=True)]
    batches = []
    for offset in range(0, len(candidates), batch_size):
        batch_candidates = tuple(candidates[offset : offset + batch_size])
        if len({candidate.image_id for candidate in batch_candidates}) != len(batch_candidates):
            raise AdminError("Duplicate image IDs are not allowed within a batch.")
        position = len(batches) + 1
        batches.append(
            CandidateBatch(
                code=f"{spec.batch_prefix}-{position:03d}",
                position=position,
                candidates=batch_candidates,
            )
        )
    return ImportPlan(**asdict(spec), batches=tuple(batches))


def import_plan(
    plan: ImportPlan,
    dsn: str,
    connect: Callable[[str], psycopg.Connection[Any]] | None = None,
) -> tuple[int, int, int]:
    return publish_candidates(
        plan,
        (CandidateChunk(batch.position, 1, batch.candidates) for batch in plan.batches),
        dsn,
        expected_batches=len(plan.batches),
        expected_items=plan.item_count,
        connect=connect,
    )


def import_file(
    path: Path,
    spec: ImportSpec,
    *,
    database: Callable[[], str] | None = None,
    shuffle_seed: int | None = None,
    method: str = "pipeline",
) -> tuple[int, int, int]:
    """Validate/close the entire source before resolving credentials or opening Postgres."""
    with (
        closing(iter_candidate_rows(path)) as rows,
        validate_candidates(rows, batch_size=spec.batch_size, shuffle_seed=shuffle_seed) as spool,
    ):
        if database is None:
            return (1, spool.batch_count, spool.item_count)
        with closing(spool.chunks()) as chunks:
            return publish_candidates(
                spec,
                chunks,
                database(),
                expected_batches=spool.batch_count,
                expected_items=spool.item_count,
                method=method,
            )


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
    parser.add_argument(
        "--shuffle-algorithm", choices=[SHUFFLE_ALGORITHM], default=SHUFFLE_ALGORITHM
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        spec = import_spec(
            campaign_code=args.campaign_code,
            internal_name=args.internal_name,
            reviewer_name=args.reviewer_name,
            batch_prefix=args.batch_prefix,
            batch_size=args.batch_size,
            status=args.status,
            target_taxon_key=args.target_taxon_key,
            target_scientific_name=args.target_scientific_name,
            source_provider=args.source_provider,
        )
        counts = import_file(
            args.input,
            spec,
            database=None if args.dry_run else database_url,
            shuffle_seed=args.shuffle_seed,
        )
    except (
        AdminError,
        OSError,
        ValueError,
        sqlite3.Error,
        pl.exceptions.PolarsError,
        psycopg.Error,
    ):
        print("Import failed. No candidate details or credentials were printed.")
        return 1
    prefix = "Dry run valid" if args.dry_run else "Import complete"
    shuffle = (
        f" shuffle={SHUFFLE_ALGORITHM} seed={args.shuffle_seed}"
        if args.shuffle_seed is not None
        else ""
    )
    print(f"{prefix}: campaigns={counts[0]} batches={counts[1]} items={counts[2]}{shuffle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
