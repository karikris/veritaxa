"""Export a private, versioned map snapshot from one live review campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tools.attach_location_clues import RestAdmin


def make_snapshot(items: list[dict], dates: dict[str, dict], title: str) -> dict:
    images, seen = [], set()
    for item in items:
        source_key = item.get("source_record_id") or item["image_id"]
        canonical = (item["source_provider"], source_key)
        if canonical in seen:
            raise ValueError("Duplicate source image in map cohort.")
        seen.add(canonical)
        tag = item.get("geotag") or {}
        try:
            point = float(tag["latitude"]), float(tag["longitude"])
        except (KeyError, ValueError, TypeError):
            raise ValueError("A selected image has no usable coordinates.") from None
        if (
            not all(math.isfinite(value) for value in point)
            or not -86 <= point[0] <= 86
            or not -180 <= point[1] <= 180
            or point == (0, 0)
        ):
            raise ValueError("A selected image has no usable coordinates.")
        record = dates.get(source_key, {})
        uploaded = None
        if record.get("posted"):
            try:
                uploaded = datetime.fromtimestamp(float(record["posted"]), UTC).isoformat()
            except (ValueError, TypeError, OverflowError):
                pass
        key = hashlib.sha256("\n".join(canonical).encode()).hexdigest()[:32]
        images.append(
            {
                "key": key,
                "latitude": point[0],
                "longitude": point[1],
                "image_url": item.get("display_url") or item["image_url"],
                "fallback_url": item["image_url"],
                "bioclip_label": item.get("model_top10") or item.get("model_top5") or "",
                "captured_at": record.get("taken"),
                "taken_unknown": str(record.get("takenunknown", "0")) == "1",
                "taken_granularity": str(record.get("takengranularity", "0")),
                "uploaded_at": uploaded,
                # Provenance stays in the private snapshot; the client projection omits it.
                "coordinate_provenance": tag.get("status"),
            }
        )
    images.sort(key=lambda row: row["key"])
    identity = json.dumps({"title": title, "images": images}, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": 1,
        "revision": hashlib.sha256(identity.encode()).hexdigest(),
        "title": title,
        "image_count": len(images),
        "images": images,
    }


def export_snapshot(campaign_code: str, env_file: Path, cache: Path, title: str) -> dict:
    api = RestAdmin(env_file)
    campaigns = api.request(
        "GET",
        "review_campaigns",
        {"campaign_code": "eq." + campaign_code, "status": "eq.open", "select": "id"},
    )
    if len(campaigns) != 1:
        raise ValueError("The requested live campaign was not found.")
    batches = api.request(
        "GET",
        "review_batches",
        {
            "campaign_id": "eq." + campaigns[0]["id"],
            "status": "eq.open",
            "select": "id",
            "order": "position",
            "limit": "1000",
        },
    )
    items = []
    for batch in batches:
        offset = 0
        while True:
            rows = api.request(
                "GET",
                "review_items",
                {
                    "batch_id": "eq." + batch["id"],
                    "select": "image_id,source_provider,source_record_id,image_url,display_url,"
                    "geotag:source_labels->_veritaxa_geotag,"
                    "model_top10:pipeline_metadata->bioclip->top10->0->>scientific_name,"
                    "model_top5:pipeline_metadata->bioclip->top5->0->>scientific_name",
                    "order": "position",
                    "offset": offset,
                    "limit": "1000",
                },
            )
            items.extend(rows)
            if len(rows) < 1000:
                break
            offset += len(rows)
    keys = {i.get("source_record_id") or i["image_id"] for i in items}
    dates = {}
    with sqlite3.connect(cache.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        for pid, status, payload in connection.execute(
            "select photo_id,status,payload from responses where endpoint='info'"
        ):
            if status == "ok" and str(pid) in keys:
                dates[str(pid)] = json.loads(payload).get("photo", {}).get("dates") or {}
    return make_snapshot(items, dates, title)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-code", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--flickr-cache", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Snapshot output already exists; use a new versioned path.")
    snapshot = export_snapshot(args.campaign_code, args.env_file, args.flickr_cache, args.title)
    if snapshot["image_count"] != args.expected_count:
        parser.error("Image count changed; inspect the cohort before publishing.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix("." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")
        temporary.chmod(0o600)
        os.link(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"images": snapshot["image_count"], "revision": snapshot["revision"]}))


if __name__ == "__main__":
    main()
