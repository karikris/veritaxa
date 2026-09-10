"""Driver-backed export gates on an explicitly configured disposable local database."""

from __future__ import annotations

import argparse
import json
import os
import re
import resource
import tempfile
import time
from pathlib import Path

import polars as pl
import psycopg
from psycopg.conninfo import conninfo_to_dict

from tools.common import AdminError
from tools.export_reviews import export_reviews


def synthetic_dsn() -> str:
    dsn = os.environ.get("VERITAXA_SYNTHETIC_DSN", "")
    params = conninfo_to_dict(dsn)
    host = params.get("host", "")
    if (
        params.get("dbname") != "veritaxa_synthetic"
        or not (
            host in {"localhost", "127.0.0.1", "::1"}
            or re.fullmatch(r"/tmp/veritaxa-postgres-[A-Za-z0-9_-]+", host)
        )
        or params.get("hostaddr", "127.0.0.1") not in {"127.0.0.1", "::1"}
        or "service" in params
        or os.environ.get("PGSERVICE")
        or os.environ.get("PGHOSTADDR", "") not in {"", "127.0.0.1", "::1"}
    ):
        raise AdminError(
            "Set VERITAXA_SYNTHETIC_DSN to a disposable local veritaxa_synthetic database."
        )
    return dsn


def seed_campaign(connection: psycopg.Connection, count: int) -> None:
    if not 1 <= count <= 100000:
        raise AdminError("Synthetic item count must be between 1 and 100000.")
    connection.execute(
        "insert into public.review_campaigns values (%s, %s, 'Papilio exemplaris')",
        (count, f"SYNTH-{count}"),
    )
    connection.execute(
        """
        insert into public.review_batches
        select %s::bigint * 1000 + n, %s, %s || '-' || lpad((1000-n)::text, 4, '0'), n
        from generate_series(1, %s) as n
        """,
        (count, count, f"SYNTH-{count}", (count + 999) // 1000),
    )
    connection.execute(
        """
        insert into public.review_items
        select %s::bigint * 1000000 + n, %s::bigint * 1000 + (n-1)/1000 + 1,
               (n-1)%%1000 + 1, 'synthetic-' || n, 'synthetic', n::text,
               'https://images.example.invalid/' || n || '.jpg', null,
               case when n%%2 = 0 then '' else null end,
               jsonb_build_object('Unicode', '🦋', 'nested', jsonb_build_array(null, true, '')),
               jsonb_build_object('ordinal', n, 'payload', repeat(md5(n::text), 640),
                                  'nested', jsonb_build_array(
                                      jsonb_build_object('name', '🦋', 'value', 0.25)))
        from generate_series(1, %s) as n
        """,
        (count, count, count),
    )
    connection.execute(
        """
        insert into public.image_reviews
        select item.id * 10 + vote, item.id,
               ('10000000-0000-0000-0000-' || lpad(vote::text, 12, '0'))::uuid,
               case item.position%%4 when 0 then 'moth'
                    when 1 then case vote when 1 then 'plant' else 'bird' end
                    when 2 then case when vote < 3 then 'adult_butterfly' else 'plant' end
                    else 'uncertain' end,
               case when vote = 1 then null else 'Synthetic comment 🦋' end,
               null, null, 'Synthetic reviewer ' || vote,
               '2026-09-01T00:00:00Z'::timestamptz + vote * interval '1 second',
               '2026-09-10T00:00:00Z'::timestamptz + vote * interval '1 second',
               'synthetic-client'
        from public.review_items as item
        join public.review_batches as batch on batch.id = item.batch_id
        cross join generate_series(1, 3) as vote
        where batch.campaign_id = %s
          and vote <= case item.position%%4 when 0 then 3 when 1 then 2 when 2 then 3 else 1 end
        """,
        (count,),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["init", "seed", "run"])
    parser.add_argument("rows", type=int, nargs="?", default=10000)
    parser.add_argument("--consensus", action="store_true")
    parser.add_argument("--lean", action="store_true")
    parser.add_argument("--format", choices=["csv", "parquet"], default="parquet")
    args = parser.parse_args()
    dsn = synthetic_dsn()
    if args.mode in {"init", "seed"}:
        with psycopg.connect(dsn) as connection:
            if args.mode == "init":
                connection.execute(Path(__file__).with_name("export_fixture.sql").read_text())
            else:
                seed_campaign(connection, args.rows)
        print(f"Synthetic database {args.mode} complete.")
        return
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="veritaxa-export-benchmark-") as temporary:
        output = Path(temporary) / f"synthetic.{args.format}"
        exported = export_reviews(
            dsn,
            f"SYNTH-{args.rows}",
            output,
            consensus=args.consensus,
            derived=True,
            lean=args.lean,
        )
        expected = (
            args.rows if args.consensus else (args.rows // 4 * 9 + [0, 2, 5, 6][args.rows % 4])
        )
        if exported != expected:
            raise AdminError("Synthetic row count did not match the seeded fixture.")
        print(
            json.dumps(
                {
                    "items": args.rows,
                    "exported_rows": exported,
                    "consensus": args.consensus,
                    "lean": args.lean,
                    "format": args.format,
                    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                    "seconds": time.monotonic() - started,
                    "output_bytes": output.stat().st_size,
                    "polars_threads": pl.thread_pool_size(),
                }
            )
        )


if __name__ == "__main__":
    main()
