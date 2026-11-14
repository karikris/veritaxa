"""Publish exploratory geotag labels without rewriting the larger source evidence."""

from __future__ import annotations

import argparse
import gzip
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tools.attach_location_clues import RestAdmin
from tools.common import AdminError
from tools.provisional_geotags import GEOTAG_KEY


def merge_labels(row, plan):
    if (row["id"], row["source_provider"], row["source_record_id"]) != (
        plan["item_id"],
        plan["source_provider"],
        plan["source_record_id"],
    ):
        raise AdminError("Geotag plan identity differs from the live image.")
    labels = row.get("source_labels") or {}
    existing = labels.get(GEOTAG_KEY)
    if (
        existing
        and existing != plan["geotag"]
        and existing.get("status") not in {"provisional", "unresolved", "source_reported"}
    ):
        raise AdminError("A reviewed geotag cannot be overwritten.")
    return {**labels, GEOTAG_KEY: plan["geotag"]}


def publish_one(client, row, plan):
    for _ in range(3):
        merged = merge_labels(row, plan)
        if merged == row.get("source_labels"):
            return "already_present"
        old = row.get("source_labels")
        params = {
            "id": "eq." + row["id"],
            "batch_id": "eq." + row["batch_id"],
            "source_labels": "is.null"
            if old is None
            else "eq." + json.dumps(old, separators=(",", ":"), ensure_ascii=False),
            "select": "id,source_labels",
        }
        result = client.request("PATCH", "review_items", params, {"source_labels": merged})
        if len(result) == 1:
            if result[0]["source_labels"] != merged:
                raise AdminError("Geotag read-back mismatch.")
            return "attached"
        if result:
            raise AdminError("Unexpected geotag update count.")
        fresh = client.request(
            "GET",
            "review_items",
            {
                "select": "id,batch_id,source_provider,source_record_id,source_labels",
                "id": "eq." + row["id"],
            },
        )
        if len(fresh) != 1 or fresh[0]["batch_id"] != row["batch_id"]:
            raise AdminError("Image moved during geotag update.")
        row = fresh[0]
    raise AdminError("Concurrent label changes prevented update.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    with gzip.open(args.plan, "rt") as f:
        plans = [json.loads(line) for line in f if line.strip()]
    if len({p["item_id"] for p in plans}) != len(plans):
        raise AdminError("Duplicate geotag targets.")
    client = RestAdmin(args.env_file)
    rows = {}
    for start in range(0, len(plans), 150):
        ids = ",".join(p["item_id"] for p in plans[start : start + 150])
        part = client.request(
            "GET",
            "review_items",
            {
                "select": "id,batch_id,source_provider,source_record_id,source_labels",
                "id": "in.(" + ids + ")",
                "limit": 150,
            },
        )
        rows.update((r["id"], r) for r in part)
    if len(rows) != len(plans):
        raise AdminError("Some geotag targets are missing.")
    for p in plans:
        merge_labels(rows[p["item_id"]], p)
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = args.output / "source-labels-before.json.gz"
    if not backup.exists():
        with gzip.open(backup, "wt") as f:
            json.dump(list(rows.values()), f)
        backup.chmod(0o600)
    print(json.dumps({"validated": len(plans), "publish": args.publish}), flush=True)
    if not args.publish:
        return
    counts = {"attached": 0, "already_present": 0, "failed": 0}
    with (
        (args.output / "results.jsonl").open("a") as log,
        ThreadPoolExecutor(max_workers=6) as pool,
    ):
        futures = {pool.submit(publish_one, client, rows[p["item_id"]], p): p for p in plans}
        for future in as_completed(futures):
            p = futures[future]
            try:
                state = future.result()
                record = {"item_id": p["item_id"], "state": state}
            except Exception as error:
                state = "failed"
                record = {
                    "item_id": p["item_id"],
                    "state": state,
                    "error": str(error) if isinstance(error, AdminError) else type(error).__name__,
                }
            counts[state] += 1
            log.write(json.dumps(record) + "\n")
            log.flush()
            if sum(counts.values()) % 250 == 0:
                print(json.dumps(counts), flush=True)
    (args.output / "result.json").write_text(json.dumps(counts, indent=2))
    print(json.dumps(counts), flush=True)
    if counts["failed"]:
        raise AdminError("Some geotags require retry; completed updates are preserved.")


if __name__ == "__main__":
    try:
        main()
    except AdminError as error:
        raise SystemExit(str(error)) from None
