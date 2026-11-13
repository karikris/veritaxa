"""Reproduce common-match counts, deterministic samples, and coordinate findings."""

import argparse
from pathlib import Path

import polars as pl

from ..common import dump


def inspect(directory, sample_size=20, seed=104):
    frame = pl.read_parquet(directory / "location_evidence.parquet")
    candidates = frame.filter(pl.col("capture_locality_candidate"))
    return {
        "raw_most_common_matches": frame.group_by("matched_text")
        .len()
        .sort("len", descending=True)
        .head(25)
        .to_dicts(),
        "candidate_most_common_matches": candidates.group_by("matched_text", "kind")
        .agg(pl.col("flickr_photo_id").n_unique().alias("images"))
        .sort("images", descending=True)
        .head(25)
        .to_dicts(),
        "deterministic_candidate_sample": candidates.sample(
            n=min(sample_size, candidates.height), seed=seed
        )
        .select("flickr_photo_id", "source", "kind", "matched_text", "excerpt", "flags")
        .to_dicts(),
        "coordinate_methods": frame.filter(pl.col("kind").str.contains("coordinate"))
        .group_by("kind")
        .agg(pl.len().alias("evidence_rows"), pl.col("flickr_photo_id").n_unique().alias("images"))
        .to_dicts(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--seed", type=int, default=104)
    args = parser.parse_args()
    print(dump(inspect(args.analysis, args.sample, args.seed)))


if __name__ == "__main__":
    main()
