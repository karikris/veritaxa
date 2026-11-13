"Summarize earlier/later anchors and relative-time narratives without assigning pins."

import argparse
from pathlib import Path

import polars as pl

from ..common import dump


def inspect(directory):
    frame = pl.read_parquet(directory / "temporal_geotagged_neighbors.parquet")
    relative = pl.read_parquet(directory / "relative_time_evidence.parquet")
    return {
        "images_per_direction_and_window": frame.group_by("relation", "time_window")
        .agg(pl.col("flickr_photo_id").n_unique().alias("images"))
        .to_dicts(),
        "earlier_examples": frame.filter(
            (pl.col("relation") == "earlier") & (pl.col("time_window") == "within_1_hour")
        )
        .sort("minutes_anchor_before_target", descending=True)
        .head(10)
        .to_dicts(),
        "narrative_types": relative.group_by("narrative_type")
        .agg(pl.col("flickr_photo_id").n_unique().alias("images"))
        .to_dicts(),
        "one_hour_narrative_examples": relative.filter(pl.col("minutes") == 60).head(12).to_dicts(),
        "limitation": (
            "Capture wall-clock time has no verified timezone. Comment times are not capture times."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    args = parser.parse_args()
    print(dump(inspect(args.analysis)))


if __name__ == "__main__":
    main()
