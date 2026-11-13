"Inspect source grain, text coverage, capture dates, authors and local cache state."

import argparse
import importlib.metadata
import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path

import polars as pl

from ..common import dump


def profile(source, cache=None):
    frame = pl.read_parquet(source)
    dates, statuses, lengths = Counter(), {}, Counter()
    comments = owner_comments = 0
    for row in frame.iter_rows(named=True):
        captured = json.loads(row.get("flickr_current_dates_json") or "{}")
        dates[str((captured.get("takengranularity"), captured.get("takenunknown")))] += 1
        owner = json.loads(row.get("flickr_current_owner_json") or "{}").get("nsid")
        for comment in json.loads(row.get("flickr_comments_json") or "[]"):
            comments += 1
            owner_comments += bool(owner and comment.get("author") == owner)
        for field in (
            "raw_title",
            "raw_description",
            "raw_tags",
            "flickr_current_title",
            "flickr_current_description",
        ):
            lengths[field] += len(row.get(field) or "")
    if cache:
        with sqlite3.connect(f"file:{Path(cache).resolve()}?mode=ro", uri=True) as connection:
            statuses = connection.execute(
                "SELECT endpoint,status,count(*) FROM responses GROUP BY endpoint,status"
            ).fetchall()
    return {
        "rows": frame.height,
        "unique_photo_ids": frame["flickr_photo_id"].n_unique(),
        "columns": frame.columns,
        "capture_date_granularity_and_unknown": dict(dates),
        "visible_field_character_counts_before_html_stripping": dict(lengths),
        "comment_records": comments,
        "owner_authored_comments": owner_comments,
        "third_party_comments": comments - owner_comments,
        "cache_endpoint_states": statuses,
        "cache_scope": "Entire shared cache; the source collection may be a subset",
        "optional_tool_availability": {
            name: bool(importlib.util.find_spec(name))
            for name in ("spacy", "geonamescache", "ahocorasick", "geopy", "rapidfuzz")
        },
        "polars_version": importlib.metadata.version("polars"),
        "nlp_models_executed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    print(dump(profile(args.source, args.cache)))


if __name__ == "__main__":
    main()
