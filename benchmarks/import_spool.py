"""Spool-only synthetic probe; excludes source-file decoding and database insertion."""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import subprocess
import sys
import time

from tools.candidate_spool import validate_candidates


def synthetic_rows(count: int):
    for index in range(count):
        yield {
            "image_id": f"synthetic-{index}",
            "image_url": f"https://images.example.invalid/{index}.jpg",
            "source_provider": "synthetic",
            "pipeline_metadata": {
                "payload": hashlib.sha256(str(index).encode()).hexdigest() * 320,
                "ordinal": index,
                "nested": [None, True, "🦋"],
            },
            "extra_score": 0.25,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows", type=int)
    parser.add_argument("--shuffle-seed", type=int)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.worker:
        # A shell's final exec can inherit its launcher's ru_maxrss high-water mark.
        # Fork from this small interpreter before exec so the probe starts cleanly.
        subprocess.run(
            [sys.executable, "-m", "benchmarks.import_spool", *sys.argv[1:], "--worker"],
            check=True,
        )
        return
    baseline_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    started = time.monotonic()
    count = checksum = chunks = 0
    with validate_candidates(synthetic_rows(args.rows), shuffle_seed=args.shuffle_seed) as spool:
        assert spool.item_count == args.rows
        validated_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        for chunk in spool.chunks():
            chunks += 1
            for candidate in chunk.candidates:
                index = int(candidate.image_id.removeprefix("synthetic-"))
                if args.shuffle_seed is None:
                    assert index == count
                assert candidate.pipeline_metadata["ordinal"] == index
                assert candidate.pipeline_metadata["extra_score"] == 0.25
                count += 1
                checksum += index
    assert count == args.rows
    assert checksum == count * (count - 1) // 2
    print(
        json.dumps(
            {
                "stage": "spool-only",
                "baseline_rss_mib": baseline_rss,
                "rows": count,
                "chunks": chunks,
                "shuffle_seed": args.shuffle_seed,
                "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                "validated_rss_mib": validated_rss,
                "seconds": time.monotonic() - started,
            }
        )
    )


if __name__ == "__main__":
    main()
