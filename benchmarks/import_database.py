"""Synthetic candidate fixtures and complete importer probes on an isolated local database."""

from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pyarrow as pa
import pyarrow.parquet as parquet

from benchmarks.export_database import synthetic_dsn
from benchmarks.import_spool import synthetic_rows
from tools.common import AdminError
from tools.import_candidates import import_file
from tools.import_publish import import_spec


def import_dsn() -> str:
    return synthetic_dsn(database_name="veritaxa_import_synthetic", variable="VERITAXA_IMPORT_DSN")


def initialize(connection: psycopg.Connection) -> None:
    """Use the actual table DDL/constraints; Auth/RLS remain covered by the Supabase suite."""
    migrations = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    initial = (migrations / "20260725084043_secure_review_database.sql").read_text()
    enum_start = initial.index("create type public.campaign_status")
    enum_end = initial.index(";", initial.index("create type public.batch_status")) + 1
    connection.execute(initial[enum_start:enum_end])
    table_start = initial.index("create table public.review_campaigns")
    table_end = initial.index("create table public.image_reviews")
    connection.execute(initial[table_start:table_end])
    for migration in (
        "20260727161056_expose_flickr_keyword_review_option.sql",
        "20260728103835_expose_target_scientific_name_review_option.sql",
    ):
        table_changes = (
            (migrations / migration).read_text().split("alter table public.image_reviews", 1)[0]
        )
        connection.execute(table_changes)


def remove_campaign(connection: psycopg.Connection, code: str) -> None:
    connection.execute(
        """delete from public.review_items where batch_id in (
        select batch.id from public.review_batches batch join public.review_campaigns campaign
        on campaign.id = batch.campaign_id where campaign.campaign_code = %s)""",
        (code,),
    )
    connection.execute(
        """delete from public.review_batches where campaign_id in (
        select id from public.review_campaigns where campaign_code = %s)""",
        (code,),
    )
    connection.execute("delete from public.review_campaigns where campaign_code = %s", (code,))


def fixture_path(count: int, file_format: str) -> Path:
    root = os.environ.get("VERITAXA_IMPORT_FIXTURES")
    if not root:
        raise AdminError("Set VERITAXA_IMPORT_FIXTURES to a private synthetic fixture directory.")
    return Path(root) / f"synthetic-{count}.{file_format}"


def generate(count: int, file_format: str) -> None:
    path = fixture_path(count, file_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("image_id", pa.string()),
            ("image_url", pa.string()),
            ("source_provider", pa.string()),
            ("pipeline_metadata", pa.string()),
            ("extra_score", pa.float64()),
        ]
    )
    rows = (
        {
            **row,
            "pipeline_metadata": json.dumps(
                row["pipeline_metadata"], ensure_ascii=False, separators=(",", ":")
            ),
        }
        for row in synthetic_rows(count)
    )
    # Explicit exclusive creation: never replace an existing fixture or user file.
    with path.open("xb") as output:
        if file_format == "parquet":
            with parquet.ParquetWriter(
                output, schema, compression="zstd", use_dictionary=False
            ) as writer:
                pending = []
                for row in rows:
                    pending.append(row)
                    if len(pending) == 64:
                        writer.write_batch(pa.RecordBatch.from_pylist(pending, schema=schema))
                        pending.clear()
                if pending:
                    writer.write_batch(pa.RecordBatch.from_pylist(pending, schema=schema))
        elif file_format == "ndjson":
            for row in rows:
                output.write((json.dumps(row, ensure_ascii=False) + "\n").encode())
        else:
            from io import TextIOWrapper

            with TextIOWrapper(output, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=schema.names, quoting=csv.QUOTE_NOTNULL)
                writer.writeheader()
                writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["init", "generate", "run"])
    parser.add_argument("rows", nargs="?", type=int, default=10000)
    parser.add_argument("--format", choices=["parquet", "csv", "ndjson"], default="parquet")
    parser.add_argument("--method", choices=["pipeline", "copy"], default="pipeline")
    parser.add_argument("--shuffle-seed", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.mode == "init":
        with psycopg.connect(import_dsn()) as connection:
            initialize(connection)
        print("Synthetic import database initialized.")
        return
    if args.mode == "generate":
        generate(args.rows, args.format)
        print(f"Synthetic fixture ready: rows={args.rows} format={args.format}")
        return
    if not args.worker:
        subprocess.run(
            [sys.executable, "-m", "benchmarks.import_database", *sys.argv[1:], "--worker"],
            check=True,
        )
        return
    dsn = None if args.dry_run else import_dsn()
    code = "SYNTH-MEM-" + uuid4().hex
    spec = import_spec(
        campaign_code=code,
        internal_name="Synthetic memory probe",
        reviewer_name="Synthetic",
        batch_prefix=code,
        target_scientific_name="Papilio exemplaris",
        status="open",
    )
    started = time.monotonic()
    published = False
    try:
        counts = import_file(
            fixture_path(args.rows, args.format),
            spec,
            database=(lambda: dsn) if dsn else None,
            shuffle_seed=args.shuffle_seed,
            method=args.method,
        )
        published = dsn is not None
        assert counts == (1, (args.rows + 999) // 1000, args.rows)
        elapsed = time.monotonic() - started
        if dsn:
            with psycopg.connect(dsn) as connection:
                actual = connection.execute(
                    """select count(*), sum((item.pipeline_metadata->>'ordinal')::bigint),
                    min(length(item.pipeline_metadata->>'payload')),
                    max(length(item.pipeline_metadata->>'payload'))
                    from public.review_items item
                    join public.review_batches batch on batch.id=item.batch_id
                    join public.review_campaigns campaign on campaign.id=batch.campaign_id
                    where campaign.campaign_code=%s""",
                    (code,),
                ).fetchone()
                assert actual == (args.rows, args.rows * (args.rows - 1) // 2, 20480, 20480)
        print(
            json.dumps(
                {
                    "rows": args.rows,
                    "format": args.format,
                    "method": args.method,
                    "shuffle_seed": args.shuffle_seed,
                    "dry_run": args.dry_run,
                    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                    "seconds": elapsed,
                }
            ),
            flush=True,
        )
    finally:
        if published:
            with psycopg.connect(dsn) as connection:
                remove_campaign(connection, code)


if __name__ == "__main__":
    main()
