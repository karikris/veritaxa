"""Resume metadata/comments for two collections, after geotagged discovery ends."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import time
from pathlib import Path

import polars as pl

from tools.join_flickr_reviews import (
    build_rows,
    digest,
    load_reviews,
    now,
    open_cache,
    refresh,
    write_outputs,
)

TERMINAL = {"ok", "photo_unavailable"}


def seed_queue(cache, geotagged_ids, original_ids):
    cache.execute("""CREATE TABLE IF NOT EXISTS combined_enrichment_queue (
        photo_id TEXT, endpoint TEXT, priority INTEGER, state TEXT, failed_passes INTEGER DEFAULT 0,
        PRIMARY KEY(photo_id,endpoint))""")
    for priority, ids in enumerate((geotagged_ids, original_ids)):
        for pid in sorted(set(ids)):
            for endpoint in ("info", "comments"):
                existing = cache.execute(
                    "SELECT status FROM responses WHERE photo_id=? AND endpoint=?", (pid, endpoint)
                ).fetchone()
                state = "complete" if existing and existing[0] in TERMINAL else "pending"
                cache.execute(
                    """INSERT INTO combined_enrichment_queue VALUES (?,?,?,?,0)
                    ON CONFLICT(photo_id,endpoint) DO UPDATE
                    SET priority=min(priority,excluded.priority)""",
                    (pid, endpoint, priority, state),
                )
    cache.commit()


def publish_collection(source, reviews, cache, output):
    output.mkdir(parents=True, exist_ok=True)
    stage = output / ".combined-checkpoint"
    stage.mkdir(exist_ok=True)
    ids = set(source["flickr_photo_id"])
    selected_reviews = [r for r in reviews if r["metadata.flickr_photo_id"] in ids]
    result = write_outputs(
        build_rows(source, selected_reviews, cache),
        stage,
        {"source_rows": source.height, "enrichment": "info and comments; cached responses reused"},
    )
    for name in (
        "joined_images.csv",
        "joined_images.parquet",
        "column_dictionary.json",
        "manifest.json",
    ):
        os.replace(stage / name, output / name)
    return result["counts"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-dir", type=Path, required=True)
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--secrets-env", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--reviews-sha256", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "combined_enrichment.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Also own the original recovery lock, preventing two enrichment workers.
    original_lock = (args.output / "recovery.lock").open("a+")
    fcntl.flock(original_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    status_path = args.output / "combined_enrichment_status.json"

    def status(state, cache=None):
        data = {
            "state": state,
            "pid": os.getpid(),
            "updated_at_utc": now(),
            "priority": "geotagged first, original non-geotagged second",
            "endpoints": ["info", "comments"],
        }
        if cache is not None:
            data["queue"] = [
                dict(priority=p, endpoint=e, state=s, requests=n)
                for p, e, s, n in cache.execute(
                    "SELECT priority,endpoint,state,count(*) FROM combined_enrichment_queue "
                    "GROUP BY priority,endpoint,state"
                )
            ]
        temp = status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(temp, status_path)
        print(json.dumps(data), flush=True)

    while json.loads((args.discovery_dir / "manifest.json").read_text())["status"] != "complete":
        status("waiting_for_geotagged_discovery")
        time.sleep(30)
    geo_path = args.discovery_dir / "geotagged_source_records.parquet"
    geotagged, original = pl.read_parquet(geo_path), pl.read_parquet(args.original_source)
    if (
        not geotagged.height
        or geotagged.filter(
            pl.col("latitude").is_null()
            | pl.col("longitude").is_null()
            | ~pl.col("latitude").is_between(-90, 90)
            | ~pl.col("longitude").is_between(-180, 180)
            | ~pl.col("accuracy").is_between(1, 16)
        ).height
    ):
        raise ValueError("Discovery input contains invalid geotags")
    reviews = load_reviews(args.reviews, args.reviews_sha256)
    key = None
    for line in args.secrets_env.read_text().splitlines():
        match = re.match(r"^\s*(?:export\s+)?FLICKR_API_KEY\s*=\s*(.*)$", line)
        if match:
            values = shlex.split(match[1], comments=True)
            key = values[0] if values else None
            break
    if not key:
        raise ValueError("Flickr key unavailable in configured secret file")
    cache = open_cache(args.output / "flickr_refresh.sqlite")
    seed_queue(cache, geotagged["flickr_photo_id"], original["flickr_photo_id"])
    plan = {
        "created_at_utc": now(),
        "geotagged_images": geotagged.height,
        "original_images": original.height,
        "unique_images": len(set(geotagged["flickr_photo_id"]) | set(original["flickr_photo_id"])),
        "source_sha256": {str(p): digest(p) for p in (geo_path, args.original_source)},
        "endpoints": ["flickr.photos.getInfo", "flickr.photos.comments.getList"],
        "priority": "geotagged first",
        "reuse_completed": True,
    }
    (args.output / "combined_enrichment_plan.json").write_text(json.dumps(plan, indent=2) + "\n")

    def checkpoint():
        publish_collection(geotagged, reviews, cache, args.output / "geotagged")
        publish_collection(original, reviews, cache, args.output)

    calls_since_checkpoint = 0
    checkpoint()
    status("running", cache)
    while True:
        task = cache.execute(
            "SELECT photo_id,endpoint,failed_passes FROM combined_enrichment_queue "
            "WHERE state='pending' ORDER BY priority,failed_passes,photo_id,endpoint LIMIT 1"
        ).fetchone()
        if task is None:
            break
        pid, endpoint, failures = task
        made = refresh([pid], cache, key, 4, endpoints=[endpoint])
        calls_since_checkpoint += made
        response = cache.execute(
            "SELECT status FROM responses WHERE photo_id=? AND endpoint=?", (pid, endpoint)
        ).fetchone()
        if response and response[0] in TERMINAL:
            cache.execute(
                "UPDATE combined_enrichment_queue SET state='complete' "
                "WHERE photo_id=? AND endpoint=?",
                (pid, endpoint),
            )
        elif made:
            failures += 1
            cache.execute(
                "UPDATE combined_enrichment_queue SET failed_passes=?,state=? "
                "WHERE photo_id=? AND endpoint=?",
                (failures, "failed" if failures >= 3 else "pending", pid, endpoint),
            )
        cache.commit()
        if made == 0:
            status("waiting_for_api_budget", cache)
            time.sleep(30)
        elif calls_since_checkpoint >= 200:
            checkpoint()
            calls_since_checkpoint = 0
            status("running", cache)
        elif calls_since_checkpoint % 20 == 0:
            status("running", cache)
    checkpoint()
    failed = cache.execute(
        "SELECT count(*) FROM combined_enrichment_queue WHERE state='failed'"
    ).fetchone()[0]
    status("complete_with_failures" if failed else "complete", cache)
    cache.close()


if __name__ == "__main__":
    main()
