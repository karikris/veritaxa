"""Fresh-process RSS gate for the complete synthetic database-to-file export path."""

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

from benchmarks.export_database import synthetic_dsn

SIZES = (10000, 100000)
MAX_RSS_MIB = 256
MAX_GROWTH_MIB = 64


def summarize(runs: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries = []
    for consensus, lean, file_format in product((False, True), (False, True), ("csv", "parquet")):
        sizes = []
        for size in SIZES:
            selected = [
                run
                for run in runs
                if (run["consensus"], run["lean"], run["format"], run["items"])
                == (consensus, lean, file_format, size)
            ]
            rss = [run["peak_rss_mib"] for run in selected]
            sizes.append(
                {
                    "items": size,
                    "rss_median_mib": statistics.median(rss),
                    "rss_range_mib": [min(rss), max(rss)],
                    "seconds_median": statistics.median(run["seconds"] for run in selected),
                }
            )
        growth = sizes[1]["rss_median_mib"] - sizes[0]["rss_median_mib"]
        summaries.append(
            {
                "consensus": consensus,
                "lean": lean,
                "format": file_format,
                "sizes": sizes,
                "rss_growth_mib": growth,
                "passed": all(size["rss_range_mib"][1] <= MAX_RSS_MIB for size in sizes)
                and growth <= MAX_GROWTH_MIB,
            }
        )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("At least three fresh runs are required for each case.")
    if sys.platform != "linux":
        parser.error("This RSS gate uses Linux ru_maxrss units.")
    with psycopg.connect(synthetic_dsn()) as connection:
        server_version = connection.info.server_version
    runs = []
    for repeat, consensus, lean, file_format, size in product(
        range(args.runs), (False, True), (False, True), ("csv", "parquet"), SIZES
    ):
        command = [
            sys.executable,
            "-m",
            "benchmarks.export_database",
            "run",
            str(size),
            "--format",
            file_format,
        ]
        if consensus:
            command.append("--consensus")
        if lean:
            command.append("--lean")
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=True)
        run = json.loads(result.stdout)
        run["repeat"] = repeat + 1
        runs.append(run)
        print(json.dumps(run), flush=True)
    summaries = summarize(runs)
    report = {
        "fixture": "synthetic-v1: 20 KiB payload plus nested JSON, 1-3 reviews/item",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "postgres": server_version,
            "packages": {package: version(package) for package in ("psycopg", "polars", "pyarrow")},
        },
        "limits": {"rss_mib": MAX_RSS_MIB, "median_growth_mib": MAX_GROWTH_MIB},
        "summaries": summaries,
        "runs": runs,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    passed = all(summary["passed"] for summary in summaries)
    print("Export memory gate " + ("passed." if passed else "failed."))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
