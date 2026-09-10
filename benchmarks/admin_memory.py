"""Synthetic-only profiling of unchanged VeriTaxa admin functions. No database I/O."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import polars as pl

from tools.export_reviews import (
    EXPORT_COLUMNS,
    build_consensus_export,
    fetch_export_frame,
)
from tools.import_candidates import build_import_plan, read_candidate_frame

ROOT = Path(os.environ["VERITAXA_AUDIT_FIXTURES"]).resolve()
METADATA_BYTES = 20_480


def payload(index: int) -> str:
    seed = hashlib.sha256(f"synthetic-{index}".encode()).hexdigest()
    return (seed * ((METADATA_BYTES // len(seed)) + 1))[:METADATA_BYTES]


def plan_for(frame: pl.DataFrame):
    return build_import_plan(
        frame,
        campaign_code="SYNTH-AUDIT",
        internal_name="Synthetic memory diagnostic",
        reviewer_name="Synthetic reviewer",
        batch_prefix="SYNTH",
        target_scientific_name="Papilio exemplaris",
    )


def output(stage: str, **values):
    print(
        json.dumps(
            {
                "stage": stage,
                "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
                **values,
            }
        ),
        flush=True,
    )


def generate(count: int):
    ROOT.mkdir(parents=True, exist_ok=True)
    records = (
        {
            "image_id": f"synthetic-{index:08d}",
            "image_url": f"https://images.example.invalid/{index}.jpg",
            "source_provider": "synthetic",
            "pipeline_metadata": json.dumps(
                {"synthetic_payload": payload(index), "ordinal": index}
            ),
        }
        for index in range(count)
    )
    frame = pl.DataFrame(records)
    frame.write_parquet(ROOT / f"synthetic-{count}.parquet", row_group_size=500)
    output("fixture", count=count, logical_mib=round(frame.estimated_size("mb"), 2))


def export_row(index: int):
    record = {column: None for column in EXPORT_COLUMNS}
    record.update(
        campaign_code="SYNTH-AUDIT",
        target_scientific_name="Papilio exemplaris",
        batch_code=f"SYNTH-{index // 1000:04d}",
        image_id=f"synthetic-{index:08d}",
        source_provider="synthetic",
        source_record_id=str(index),
        image_url=f"https://images.example.invalid/{index}.jpg",
        pipeline_metadata={"synthetic_payload": payload(index), "ordinal": index},
        source_labels={"synthetic": True},
        human_label="plant",
        reviewer_uuid="10000000-0000-0000-0000-000000000001",
        identifiedBy="Synthetic reviewer",
        reviewed_at=datetime(2026, 9, 10, tzinfo=UTC),
        schema_version="veritaxa-review-label-v3",
        client_version="veritaxa-web/0.2.0",
    )
    return tuple(record[column] for column in EXPORT_COLUMNS)


class SyntheticCursor:
    def __init__(self, count):
        self.count = count

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, *_):
        pass

    def fetchall(self):
        return [export_row(index) for index in range(self.count)]


class SyntheticConnection:
    def __init__(self, count):
        self.count = count

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def cursor(self):
        return SyntheticCursor(self.count)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=[
            "generate",
            "import",
            "export",
            "consensus",
            "bounded-validator-probe",
        ],
    )
    parser.add_argument("count", type=int)
    args = parser.parse_args()
    if args.mode == "generate":
        generate(args.count)
        return
    output(
        "baseline",
        mode=args.mode,
        rows=args.count,
        metadata_bytes_per_row=METADATA_BYTES,
    )
    started = time.perf_counter()
    if args.mode == "import":
        frame = read_candidate_frame(ROOT / f"synthetic-{args.count}.parquet")
        output("read", logical_mib=round(frame.estimated_size("mb"), 2))
        plan = plan_for(frame)
        assert plan.item_count == args.count
        output("plan", rows=plan.item_count, batches=len(plan.batches))
    elif args.mode == "bounded-validator-probe":
        total = 0
        digest = hashlib.sha256()
        for frame in pl.scan_parquet(ROOT / f"synthetic-{args.count}.parquet").collect_batches(
            chunk_size=500, maintain_order=True
        ):
            plan = plan_for(frame)
            total += plan.item_count
            for batch in plan.batches:
                for item in batch.candidates:
                    digest.update(item.image_id.encode())
            del plan
        assert total == args.count
        expected = hashlib.sha256(
            "".join(f"synthetic-{index:08d}" for index in range(args.count)).encode()
        ).hexdigest()
        assert digest.hexdigest() == expected
        output("bounded_validation_only", rows=total, id_order_sha256=digest.hexdigest())
    else:
        with patch(
            "tools.export_reviews.psycopg.connect",
            return_value=SyntheticConnection(args.count),
        ):
            frame = fetch_export_frame("synthetic-no-connection", "SYNTH-AUDIT")
        assert frame.height == args.count
        output("export_frame", logical_mib=round(frame.estimated_size("mb"), 2))
        if args.mode == "consensus":
            frame = build_consensus_export(frame)
            assert frame.height == args.count
            output("consensus_frame", logical_mib=round(frame.estimated_size("mb"), 2))
    output(
        "done",
        seconds=round(time.perf_counter() - started, 3),
        polars=pl.__version__,
        python=sys.version.split()[0],
    )


if __name__ == "__main__":
    main()
