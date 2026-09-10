"""Synthetic end-to-end writer probe; run each size in a fresh process."""

from __future__ import annotations

import argparse
import json
import resource
import tempfile
import time
from pathlib import Path

import polars as pl

from tools.tabular_output import write_records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rows", type=int)
    parser.add_argument("--format", choices=["csv", "parquet"], default="parquet")
    args = parser.parse_args()
    started = time.monotonic()
    schema = pl.Schema({"image_id": pl.String, "pipeline_metadata": pl.String})
    with tempfile.TemporaryDirectory(prefix="veritaxa-writer-benchmark-") as temporary:
        output = Path(temporary) / f"synthetic.{args.format}"
        records = (
            {
                "image_id": f"synthetic-{index:09}",
                "pipeline_metadata": json.dumps({"ordinal": index, "payload": "x" * 20480}),
            }
            for index in range(args.rows)
        )
        count = write_records(records, schema, output)
        print(
            json.dumps(
                {
                    "rows": count,
                    "format": args.format,
                    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                    "seconds": time.monotonic() - started,
                    "polars_threads": pl.thread_pool_size(),
                    "output_bytes": output.stat().st_size,
                }
            )
        )


if __name__ == "__main__":
    main()
