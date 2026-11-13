"""Compare normalized Flickr machine tags with punctuation-preserving raw tags."""

import argparse
import json
from pathlib import Path

import polars as pl

from ..common import dump
from ..coordinates import COORD_TAG, coordinate_tags


def inspect(source):
    results = []
    for row in pl.read_parquet(source).iter_rows(named=True):
        tags = json.loads(row.get("flickr_current_tags_json") or "{}").get("tag", [])
        raw = [t.get("raw") for t in tags if COORD_TAG.search(t.get("raw") or "")]
        normalized = row.get("machine_tags") or ""
        if not raw and not COORD_TAG.search(normalized):
            continue
        results.append(
            {
                "flickr_photo_id": row["flickr_photo_id"],
                "normalized_machine_tags": normalized,
                "raw_coordinate_tags": raw,
                "extracted_coordinate_pair": coordinate_tags(row),
                "review_note": "Use raw tags to preserve signs and decimal points.",
            }
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    print(dump(inspect(args.source)))


if __name__ == "__main__":
    main()
