"""Local historical reconciliation; never publish the generated data to Git.

Run with a Python environment containing Polars. Refresh is optional and requires
FLICKR_API_KEY. Each endpoint result is cached separately for safe restarts.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

METHODS = {
    "info": "flickr.photos.getInfo",
    "geo": "flickr.photos.geo.getLocation",
    "comments": "flickr.photos.comments.getList",
}


def now():
    return datetime.now(UTC).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def clean_review(value):
    if isinstance(value, dict):
        return {
            k: clean_review(v)
            for k, v in value.items()
            if "email" not in k.lower() and k != "database_review_json"
        }
    if isinstance(value, list):
        return [clean_review(v) for v in value]
    return value


def load_reviews(path, expected_sha256):
    raw = gzip.decompress(Path(path).read_bytes())
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Review snapshot checksum differs from pinned snapshot")
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def open_cache(path):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS responses (
          photo_id TEXT, endpoint TEXT, status TEXT, payload TEXT,
          retrieved_at TEXT, PRIMARY KEY(photo_id, endpoint));
        CREATE TABLE IF NOT EXISTS calls (at REAL NOT NULL);
    """)
    return c


def fetch_endpoint(photo_id, endpoint, key):
    params = urllib.parse.urlencode(
        dict(
            method=METHODS[endpoint],
            photo_id=photo_id,
            api_key=key,
            format="json",
            nojsoncallback=1,
        )
    )
    # Never log request URLs: they contain the application key.
    with urllib.request.urlopen("https://api.flickr.com/services/rest/?" + params, timeout=30) as r:
        return json.load(r)


def response_status(payload, endpoint, photo_id):
    if payload.get("stat") == "fail":
        code = str(payload.get("code"))
        if code == "1":
            return "photo_unavailable"
        if endpoint == "geo" and code == "2":
            return "no_public_location"
        if code in ("100", "96", "97", "98", "99"):
            return "invalid_credentials"
        return "failed"
    if payload.get("stat") != "ok":
        return "failed"
    body = payload.get("comments" if endpoint == "comments" else "photo")
    if not isinstance(body, dict):
        return "failed"
    identity = body.get("photo_id" if endpoint == "comments" else "id")
    if str(identity) != photo_id:
        return "failed"
    return "ok"


def refresh(ids, cache, key, max_calls, fetch=fetch_endpoint, endpoints=None):
    made = 0
    for index, pid in enumerate(ids):
        for endpoint in METHODS if endpoints is None else endpoints:
            previous = cache.execute(
                "SELECT status FROM responses WHERE photo_id=? AND endpoint=?", (pid, endpoint)
            ).fetchone()
            if previous and previous[0] in ("ok", "photo_unavailable", "no_public_location"):
                continue
            for attempt in range(4):
                if made >= max_calls:
                    return made
                # Shared durable rolling-hour ledger, including failed calls.
                cache.execute("BEGIN IMMEDIATE")
                used, oldest = cache.execute(
                    "SELECT count(*), min(at) FROM calls WHERE at > ?", (time.time() - 3600,)
                ).fetchone()
                if used >= 3500:
                    cache.rollback()
                    print(
                        "Hourly budget reached; resume after",
                        datetime.fromtimestamp(oldest + 3601, UTC).isoformat(),
                        flush=True,
                    )
                    return made
                cache.execute("INSERT INTO calls VALUES (?)", (time.time(),))
                cache.commit()
                made += 1
                time.sleep(1.05)
                try:
                    payload = fetch(pid, endpoint, key)
                    status = response_status(payload, endpoint, pid)
                except Exception as exc:
                    # Exception messages may contain an API URL; store only its type.
                    payload, status = {"error_type": type(exc).__name__}, "failed"
                cache.execute(
                    "INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?)",
                    (pid, endpoint, status, dumps(payload), now()),
                )
                cache.commit()
                if status == "invalid_credentials":
                    raise RuntimeError("Flickr rejected the configured credentials")
                if status != "failed":
                    break
                if attempt < 3:
                    time.sleep(2**attempt)
        if index % 100 == 0:
            print(f"Refresh: {index + 1}/{len(ids)} photos; {made} new API calls", flush=True)
    return made


def content(value):
    return value.get("_content") if isinstance(value, dict) else value


def enrichment(cache, pid):
    result = {
        "latitude": None,
        "longitude": None,
        "geolocation_accuracy_flickr_level": None,
        "geolocation_source": None,
        "flickr_current_location_json": None,
        "flickr_comments_json": None,
        "flickr_comments_retrieved_count": None,
    }
    # Declare fields even when no API responses are available.
    for name in (
        "title",
        "description",
        "tags_json",
        "license",
        "owner_json",
        "dates_json",
        "urls_json",
        "views",
        "comments_count",
    ):
        result["flickr_current_" + name] = None
    for endpoint in METHODS:
        r = cache.execute(
            "SELECT status,payload,retrieved_at FROM responses WHERE photo_id=? AND endpoint=?",
            (pid, endpoint),
        ).fetchone()
        status, payload, retrieved = (r[0], json.loads(r[1]), r[2]) if r else ("pending", {}, None)
        result[f"flickr_{endpoint}_status"] = status
        result[f"flickr_{endpoint}_retrieved_at_utc"] = retrieved
        if status != "ok":
            continue
        if endpoint == "info":
            p = payload["photo"]
            for name in ("title", "description", "license", "views"):
                result["flickr_current_" + name] = content(p.get(name))
            result["flickr_current_comments_count"] = content(p.get("comments"))
            for name in ("owner", "dates", "urls", "tags"):
                result[f"flickr_current_{name}_json"] = dumps(p[name]) if name in p else None
        elif endpoint == "geo":
            loc = payload["photo"].get("location", {})
            try:
                lat, lon = float(loc["latitude"]), float(loc["longitude"])
                accuracy = int(loc.get("accuracy", 0))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == lon == accuracy == 0):
                    raise ValueError("Invalid location")
            except (KeyError, TypeError, ValueError):
                result["flickr_geo_status"] = "invalid_location"
            else:
                result.update(
                    latitude=lat,
                    longitude=lon,
                    geolocation_accuracy_flickr_level=accuracy,
                    geolocation_source=METHODS["geo"],
                    flickr_current_location_json=dumps(loc),
                )
        else:
            comments = payload["comments"].get("comment", [])
            result["flickr_comments_json"] = dumps(comments)
            result["flickr_comments_retrieved_count"] = len(comments)
    return result


def build_rows(source, reviews, cache):
    records = source.to_dicts()
    keys = {(r["source"], r["flickr_photo_id"]) for r in records}
    if len(keys) != len(records):
        raise ValueError("Duplicate source identity")
    indexed = {}
    for review in reviews:
        key = (review["source_provider"], review["metadata.flickr_photo_id"])
        if key not in keys or key in indexed:
            raise ValueError("Unmatched or duplicated review identity")
        indexed[key] = review
    output = []
    for original in records:
        row = {}
        for name, value in original.items():
            # Historical coordinates are placeholders; current coordinates have one home.
            if name in ("latitude", "longitude", "accuracy"):
                continue
            if name in ("comments_text", "comments_count"):
                name = "discovery_" + name
            row[name] = dumps(value) if isinstance(value, (dict, list)) else value
        review = indexed.get((original["source"], original["flickr_photo_id"]))
        row["has_saved_review"] = review is not None
        row["veritaxa_image_id"] = review["image_id"] if review else None
        for round_name in ("first_round", "second_round"):
            for field in (
                "review_count",
                "reviewer_count",
                "unanimous",
                "unanimous_result",
                "strict_majority_result",
                "has_conflicting_reviews",
                "first_saved_at_utc",
                "last_updated_at_utc",
                "result_counts_json",
            ):
                key = f"{round_name}_{field}"
                value = review.get(key) if review else None
                if field in ("review_count", "reviewer_count"):
                    value = int(value or 0)
                elif field in ("unanimous", "has_conflicting_reviews"):
                    value = value.lower() == "true" if value else None
                row[key] = value or None if isinstance(value, str) else value
            key = f"{round_name}_reviews_json"
            row[key] = dumps(clean_review(json.loads(review[key]))) if review else "[]"
        for key in (
            "second_round_status",
            "second_round_active_queue_count",
            "second_round_queues_json",
            "export_snapshot_at_utc",
        ):
            row[key] = review.get(key) if review else None
        row.update(enrichment(cache, original["flickr_photo_id"]))
        # Geographic discovery already supplies validated geotags; metadata/comment
        # enrichment must not erase them just because geo.getLocation was not run.
        if row["latitude"] is None:
            try:
                lat, lon = float(original["latitude"]), float(original["longitude"])
                accuracy = int(original["accuracy"])
                if -90 <= lat <= 90 and -180 <= lon <= 180 and 1 <= accuracy <= 16:
                    row.update(
                        latitude=lat,
                        longitude=lon,
                        geolocation_accuracy_flickr_level=accuracy,
                        geolocation_source="flickr.photos.search",
                    )
            except (KeyError, ValueError, TypeError):
                pass
        output.append(row)
    return output


def write_outputs(rows, directory, inputs):
    # Explicit schema prevents all-null columns becoming Polars Null columns.
    schema = {k: pl.String for k in rows[0]}
    for k, v in rows[0].items():
        if isinstance(v, bool):
            schema[k] = pl.Boolean
        elif isinstance(v, int):
            schema[k] = pl.Int64
        elif isinstance(v, float):
            schema[k] = pl.Float64
    for k in ("latitude", "longitude"):
        schema[k] = pl.Float64
    for k in ("geolocation_accuracy_flickr_level", "flickr_comments_retrieved_count"):
        schema[k] = pl.Int64
    for k in frame_bool_columns(rows[0]):
        schema[k] = pl.Boolean
    frame = pl.from_dicts(rows, schema=schema, strict=False)
    base = directory / "joined_images"
    frame.write_parquet(base.with_suffix(".parquet"))
    frame.write_csv(base.with_suffix(".csv"), include_bom=True)
    roundtrip = pl.read_parquet(base.with_suffix(".parquet"))
    assert frame.equals(roundtrip)
    csv_frame = pl.read_csv(
        base.with_suffix(".csv"),
        schema_overrides={k: pl.String for k in frame.columns},
        infer_schema=False,
    )
    assert csv_frame.height == frame.height
    assert csv_frame["flickr_photo_id"].to_list() == frame["flickr_photo_id"].to_list()
    for name in frame.columns:
        if name.endswith("_json"):
            assert [json.loads(v) if v else None for v in csv_frame[name]] == [
                json.loads(v) if v else None for v in frame[name]
            ]
    counts = {"images": len(rows), "reviewed": sum(r["has_saved_review"] for r in rows)}
    counts.update(
        unreviewed=counts["images"] - counts["reviewed"],
        reviewed_percent=100 * counts["reviewed"] / counts["images"],
        first_round_reviews=sum(r["first_round_review_count"] for r in rows),
        second_round_reviews=sum(r["second_round_review_count"] for r in rows),
        disagreements=sum(bool(r["first_round_has_conflicting_reviews"]) for r in rows),
        geotagged=sum(r["latitude"] is not None for r in rows),
        unmatched_review_ids=0,
    )
    statuses = {e: dict(frame[f"flickr_{e}_status"].value_counts().iter_rows()) for e in METHODS}
    manifest = {
        "created_at_utc": now(),
        "inputs": inputs,
        "counts": counts,
        "implementation_sha256": digest(__file__),
        "scope": "Historical candidate snapshot; membership is not species verification",
        "validation": {
            "unique_image_keys": True,
            "no_join_expansion": True,
            "csv_parquet_roundtrip": True,
            "nested_json_roundtrip": True,
        },
        "enrichment_status": statuses,
        "columns": len(frame.columns),
        "outputs": {
            p.name: digest(p) for p in (base.with_suffix(".csv"), base.with_suffix(".parquet"))
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    dictionary = []
    for col in frame.columns:
        origin = (
            "Flickr API refresh"
            if col.startswith("flickr_current_")
            or col.startswith("flickr_comments_")
            or col.startswith(("flickr_info_", "flickr_geo_"))
            or col
            in ("latitude", "longitude", "geolocation_accuracy_flickr_level", "geolocation_source")
            else "VeriTaxa review snapshot"
            if col.startswith(
                ("first_round_", "second_round_", "veritaxa_", "export_snapshot_", "has_saved_")
            )
            else "Original BioMiner discovery snapshot"
        )
        mapping = col
        if col == "flickr_photo_id":
            mapping = (
                "source.flickr_photo_id = reviews.metadata.flickr_photo_id; provider also matched"
            )
        elif col == "veritaxa_image_id":
            mapping = "reviews.image_id (hash; not the Flickr photo ID)"
        elif col in ("latitude", "longitude"):
            mapping = f"photos.geo.getLocation.photo.location.{col}; historical zeros discarded"
        elif col == "geolocation_accuracy_flickr_level":
            mapping = "photos.geo.getLocation.photo.location.accuracy; Flickr level, not meters"
        elif col.endswith("_reviews_json"):
            mapping = "reviews." + col + "; redundant database_review_json and email fields removed"
        elif col.startswith("discovery_comments_"):
            mapping = "source." + col.removeprefix("discovery_")
        elif col == "has_saved_review":
            mapping = "At least one saved review in the pinned snapshot, regardless of agreement"
        elif col.startswith("flickr_"):
            mapping = (
                "Cached public API response; pending means not fetched, "
                "failed means attempted without success"
            )
        dictionary.append(
            {"column": col, "type": str(frame.schema[col]), "source": origin, "mapping": mapping}
        )
    (directory / "column_dictionary.json").write_text(json.dumps(dictionary, indent=2) + "\n")
    return manifest


def frame_bool_columns(row):
    return [
        k
        for k in row
        if k.endswith(("_unanimous", "_has_conflicting_reviews")) or k == "has_saved_review"
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--reviews-sha256", required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max-calls", type=int, default=3500)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reviews = load_reviews(args.reviews, args.reviews_sha256)
    source = pl.read_parquet(args.source)
    cache = open_cache(args.output / "flickr_refresh.sqlite")
    if args.refresh:
        key = os.environ.get("FLICKR_API_KEY")
        if not key:
            parser.error("Set FLICKR_API_KEY to refresh public Flickr metadata")
        refresh(sorted(source["flickr_photo_id"].to_list()), cache, key, args.max_calls)
    rows = build_rows(source, reviews, cache)
    if len(rows) != source.height:
        raise ValueError("Unexpected output population")
    result = write_outputs(
        rows,
        args.output,
        {
            "source_path": str(args.source.resolve()),
            "source_sha256": digest(args.source),
            "review_path": str(args.reviews.resolve()),
            "review_csv_sha256": args.reviews_sha256,
        },
    )
    print(json.dumps(result["counts"], indent=2))
    cache.close()


if __name__ == "__main__":
    main()
