"""Fresh-process complete import RSS gates and a controlled pipeline/COPY comparison."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
from importlib.metadata import version
from itertools import product
from pathlib import Path

import psycopg

from benchmarks.import_database import import_dsn

SIZES = (10000, 100000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.runs < 3 or sys.platform != "linux":
        parser.error("The gate requires Linux and at least three runs per case.")
    with psycopg.connect(import_dsn()) as connection:
        postgres = connection.info.server_version
    cases = [
        (file_format, seed, "pipeline")
        for file_format, seed in product(("csv", "parquet", "ndjson"), (None, 0))
    ]
    cases.append(("parquet", None, "copy"))
    runs = []
    for repeat, (file_format, seed, method), size in product(range(args.runs), cases, SIZES):
        command = [
            sys.executable,
            "-m",
            "benchmarks.import_database",
            "run",
            str(size),
            "--format",
            file_format,
            "--method",
            method,
            "--worker",
        ]
        if seed is not None:
            command.extend(["--shuffle-seed", str(seed)])
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=600)
        run = json.loads(result.stdout)
        run["repeat"] = repeat + 1
        runs.append(run)
        print(json.dumps(run), flush=True)
    summaries = []
    for file_format, seed, method in cases:
        sizes = []
        for size in SIZES:
            selected = [
                run
                for run in runs
                if (run["format"], run["shuffle_seed"], run["method"], run["rows"])
                == (file_format, seed, method, size)
            ]
            rss = [run["peak_rss_mib"] for run in selected]
            sizes.append(
                {
                    "rows": size,
                    "rss_median_mib": statistics.median(rss),
                    "rss_range_mib": [min(rss), max(rss)],
                    "seconds_median": statistics.median(run["seconds"] for run in selected),
                }
            )
        growth = sizes[1]["rss_median_mib"] - sizes[0]["rss_median_mib"]
        summaries.append(
            {
                "format": file_format,
                "shuffle_seed": seed,
                "method": method,
                "sizes": sizes,
                "rss_growth_mib": growth,
                "passed": growth <= 64 and all(size["rss_range_mib"][1] <= 256 for size in sizes),
            }
        )
    report = {
        "fixture": "synthetic-v1: 20 KiB payload plus nested metadata and unknown column",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "postgres": postgres,
            "packages": {name: version(name) for name in ("polars", "pyarrow", "psycopg")},
        },
        "limits": {"rss_mib": 256, "median_growth_mib": 64},
        "summaries": summaries,
        "runs": runs,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    passed = all(summary["passed"] for summary in summaries)
    print("Import memory gate " + ("passed." if passed else "failed."))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
