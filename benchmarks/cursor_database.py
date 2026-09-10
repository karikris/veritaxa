"""Measure selection and the complete authorized cursor RPC on synthetic local data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from benchmarks.export_database import synthetic_dsn


def selection_queries(style: str, direction: str) -> tuple[str, ...]:
    """Exact next/previous selection shapes; no auth/progress in these timings."""
    if style not in {"case", "seek"} or direction not in {"next", "previous"}:
        raise ValueError("Unknown cursor selection style or direction")
    comparison, order = (">", "asc") if direction == "next" else ("<", "desc")
    base = "select item.id from public.review_items as item where item.batch_id = %s"
    ordering = f"item.position {order}"
    if style == "case":
        return (
            f"{base} order by case when item.position {comparison} %s then 0 else 1 end, "
            + f"{ordering}, item.id {order} limit 1",
        )
    return (
        f"{base} and item.position {comparison} %s order by {ordering} limit 1",
        f"{base} order by {ordering} limit 1",
    )


def require_indexed_limit(plan: dict[str, Any], *, seek: bool) -> None:
    root = plan["Plan"]
    if root["Node Type"] != "Limit" or root["Actual Rows"] > 1:
        raise AssertionError("Cursor selection must limit output to one row")
    pending, indexes = [root], []
    while pending:
        node = pending.pop()
        kind = node["Node Type"]
        if "Sort" in kind or kind in {"Seq Scan", "Bitmap Heap Scan"}:
            raise AssertionError("Cursor selection sorted or scanned the batch")
        if kind in {"Index Scan", "Index Only Scan"}:
            indexes.append(node)
        pending.extend(node.get("Plans", []))
    if not indexes:
        raise AssertionError("Cursor selection lacks an index scan")
    for node in indexes:
        condition = node.get("Index Cond", "")
        if (
            "batch_id" not in condition
            or (seek and "position" not in condition)
            or node.get("Rows Removed by Filter", 0) > 0
            or node["Actual Rows"] > 1
        ):
            raise AssertionError(
                "Cursor must seek by batch/position without filtering visited rows"
            )


def timed(operation: Callable[[], Any], samples: int) -> dict[str, Any]:
    elapsed = []
    for i in range(samples + 10):
        start = time.perf_counter_ns()
        operation()
        if i >= 10:
            elapsed.append((time.perf_counter_ns() - start) / 1_000_000)
    ordered = sorted(elapsed)
    return {
        "p50_ms": statistics.median(elapsed),
        "p95_ms": ordered[math.ceil(0.95 * samples) - 1],
        "range_ms": [ordered[0], ordered[-1]],
        "samples_ms": elapsed,
    }


def seed(connection: psycopg.Connection, rows: int) -> tuple[uuid.UUID, uuid.UUID]:
    campaign, batch, reviewer, other = (uuid.uuid4() for _ in range(4))
    for identity in (reviewer, other):
        connection.execute(
            "insert into auth.users(id, raw_user_meta_data) values (%s, %s)",
            (identity, '{"identified_by":"Synthetic cursor benchmark"}'),
        )
    connection.execute(
        """insert into public.review_campaigns
        (id, internal_name, reviewer_name, campaign_code, target_scientific_name, status)
        values (%s, 'Synthetic cursor', 'Synthetic cursor', %s, 'Taxon example', 'open')""",
        (campaign, f"SYNTH-CURSOR-{campaign}"),
    )
    connection.execute(
        """insert into public.review_batches
        (id, campaign_id, batch_code, reviewer_name, position, status)
        values (%s, %s, %s, 'Synthetic cursor', 1, 'open')""",
        (batch, campaign, f"SYNTH-CURSOR-{batch}"),
    )
    connection.execute(
        """insert into public.review_items
        (batch_id, position, image_id, source_provider, image_url, pipeline_metadata)
        select %s, n * 2, 'synthetic-cursor-' || n, 'synthetic',
          'https://images.example.invalid/source.png',
          jsonb_build_object('ordinal', n, 'payload', repeat(md5(n::text), 640))
        from generate_series(1, %s) as n""",
        (batch, rows),
    )
    connection.execute(
        """insert into public.image_reviews
        (item_id, reviewer_id, label, submission_id, client_version, "identifiedBy")
        select item.id, reviewer, 'plant', gen_random_uuid(),
          'synthetic-cursor-benchmark', 'Synthetic cursor benchmark'
        from public.review_items item cross join (values (%s::uuid), (%s::uuid)) v(reviewer)
        where item.batch_id = %s and (reviewer = %s or item.position %% 4 = 0)""",
        (reviewer, other, batch, other),
    )
    for table in ("review_items", "image_reviews", "review_batches", "review_campaigns"):
        connection.execute(sql.SQL("analyze public.{}").format(sql.Identifier(table)))
    return batch, reviewer


def measure(connection: psycopg.Connection, style: str, rows: int, samples: int) -> list[dict]:
    # Every fixture and its reviews disappear on rollback, including on failure.
    batch, reviewer = seed(connection, rows)
    cases = []
    for name, direction, anchor in (
        ("next", "next", rows),
        ("previous", "previous", rows),
        ("next_wrap", "next", rows * 2),
        ("previous_wrap", "previous", 2),
        ("resume", "resume", None),
    ):
        expected_position = {
            "next": rows + 2,
            "previous": rows - 2,
            "next_wrap": 2,
            "previous_wrap": rows * 2,
            "resume": 2,
        }[name]
        expected_id = connection.execute(
            "select id from public.review_items where batch_id=%s and position=%s",
            (batch, expected_position),
        ).fetchone()[0]
        plans, selection = [], None
        if direction != "resume":
            queries = selection_queries(style, direction)

            def choose(
                queries: tuple[str, ...] = queries,
                anchor: int | None = anchor,
                expected_id: uuid.UUID = expected_id,
            ) -> None:
                result = connection.execute(queries[0], (batch, anchor)).fetchone()
                if result is None and len(queries) == 2:
                    result = connection.execute(queries[1], (batch,)).fetchone()
                if result != (expected_id,):
                    raise AssertionError("Selection returned the wrong synthetic item")

            selection = timed(choose, samples)
            for index, query in enumerate(queries):
                plan = connection.execute(
                    "explain (analyze, buffers, format json) " + query,
                    (batch, anchor) if index == 0 else (batch,),
                ).fetchone()[0][0]
                if style == "seek":
                    require_indexed_limit(plan, seek=index == 0)
                plans.append(plan)
        connection.execute("set local role authenticated")
        connection.execute(
            "select set_config('request.jwt.claims', %s, true)",
            (json.dumps({"sub": str(reviewer), "role": "authenticated"}),),
        )

        def rpc(
            anchor: int | None = anchor,
            direction: str = direction,
            expected_id: uuid.UUID = expected_id,
        ) -> None:
            result = connection.execute(
                "select * from public.get_review_cursor(%s, %s, %s)",
                (batch, anchor, direction),
            ).fetchall()
            if (
                len(result) != 1
                or result[0][0] != expected_id
                or result[0][9:] != (rows // 2, rows, False)
            ):
                raise AssertionError("Authorized RPC returned wrong identity or own progress")

        full = timed(rpc, samples)
        connection.execute("reset role")
        cases.append({"case": name, "selection": selection, "full_rpc": full, "plans": plans})
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("style", choices=("case", "seek"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 10 <= args.samples <= 1000:
        parser.error("--samples must be between 10 and 1000")
    if not 1 <= args.repeats <= 5:
        parser.error("--repeats must be between 1 and 5")
    dsn = synthetic_dsn(database_name="veritaxa_cursor_synthetic", variable="VERITAXA_CURSOR_DSN")
    with args.output.open("x", encoding="utf-8") as output, psycopg.connect(dsn) as connection:
        definition = connection.execute(
            "select pg_get_functiondef('public.get_review_cursor(uuid,integer,text)'::regprocedure)"
        ).fetchone()[0]
        if ("case when item.position > p_anchor_position" in definition) != (args.style == "case"):
            raise ValueError("Selected benchmark style does not match the installed cursor")
        report = {
            "style": args.style,
            "python": platform.python_version(),
            "psycopg": psycopg.__version__,
            "postgres": connection.execute("select version()").fetchone()[0],
            "function_sha256": hashlib.sha256(definition.encode()).hexdigest(),
            "samples": args.samples,
            "repeats": args.repeats,
            "notes": [
                "Synthetic local SQL database only; fixtures roll back after each size.",
                "10 warm-ups per case; timings include local driver/round-trip/row decode.",
                "Selection runs as owner; full RPC runs as authenticated with an active profile.",
                "Half the items have the caller's review; all have an independent other review.",
                "20 KiB metadata per item; 1,000 is the import batch cap; larger sizes stress it.",
                "Full RPC includes authorization, progress and response assembly, not HTTP/Auth.",
                "Resume is unchanged and has no separate selection-only timing.",
                "EXPLAIN contains synthetic UUIDs only; no task identifiers or credentials.",
            ],
            "runs": [],
        }
        connection.rollback()
        for repeat in range(1, args.repeats + 1):
            for rows in (1000, 10000, 100000):
                # Clear dead versions from previous rolled-back fixtures so old
                # synthetic runs do not inflate the next run's physical scan.
                connection.autocommit = True
                for table in (
                    "review_items",
                    "image_reviews",
                    "review_batches",
                    "review_campaigns",
                ):
                    connection.execute(
                        sql.SQL("vacuum (analyze) public.{}").format(sql.Identifier(table))
                    )
                connection.autocommit = False
                cases = measure(connection, args.style, rows, args.samples)
                connection.rollback()
                report["runs"].append({"repeat": repeat, "rows": rows, "cases": cases})
                print(json.dumps({"style": args.style, "repeat": repeat, "rows": rows}))
        json.dump(report, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
