"""Validate output joins, source preservation, evidence and temporal arithmetic."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import polars as pl


def validate(root):
    manifest = json.loads((root / "analysis_manifest.json").read_text())
    original = pl.read_parquet(root / "input_original.parquet")
    geo = pl.read_parquet(root / "input_geotagged.parquet")
    images = pl.read_parquet(root / "image_geolocation_clues.parquet")
    evidence = pl.read_parquet(root / "location_evidence.parquet")
    relative = pl.read_parquet(root / "relative_time_evidence.parquet")
    temporal = pl.read_parquet(root / "temporal_geotagged_neighbors.parquet")
    assert images.height == images["flickr_photo_id"].n_unique() == original.height
    assert set(images["flickr_photo_id"]) == set(original["flickr_photo_id"])
    assert len(images.columns) == len(set(images.columns))
    assert images["inferred_target_latitude"].null_count() == images.height
    assert images["inferred_target_longitude"].null_count() == images.height
    assert evidence["evidence_id"].n_unique() == evidence.height
    for value in images["text_coordinate_clues_json"]:
        entries = json.loads(value)
        assert len(entries) == len({json.dumps(e, sort_keys=True) for e in entries})
    for frame in [evidence, relative, temporal]:
        assert set(frame["flickr_photo_id"]) <= set(images["flickr_photo_id"])
    for name in [
        "image_geolocation_clues",
        "location_evidence",
        "relative_time_evidence",
        "temporal_geotagged_neighbors",
    ]:
        frame = pl.read_parquet(root / f"{name}.parquet")
        csv = pl.read_csv(
            root / f"{name}.csv",
            schema_overrides={k: v for k, v in frame.schema.items() if v != pl.Null},
            infer_schema_length=None,
        ).cast(frame.schema)
        assert frame.equals(csv), name
    for path, expected in manifest["source_sha256"].items():
        snapshot = root / Path(path).name
        with snapshot.open("rb") as handle:
            assert hashlib.file_digest(handle, "sha256").hexdigest() == expected
    assert images["provider_latitude"].count() == manifest["summary"]["public_coordinate_images"]
    assert (
        images.filter(pl.col("coordinate_machine_tags_json").is_not_null()).height
        == manifest["summary"]["machine_coordinate_images"]
    )
    assert temporal.filter(pl.col("flickr_photo_id") == pl.col("anchor_flickr_photo_id")).is_empty()
    source_rows = {str(r["flickr_photo_id"]): r for r in original.to_dicts() + geo.to_dicts()}
    for row in temporal.iter_rows(named=True):
        target, anchor = (
            source_rows[row["flickr_photo_id"]],
            source_rows[row["anchor_flickr_photo_id"]],
        )
        assert (
            (
                json.loads(target.get("flickr_current_owner_json") or "{}").get("nsid")
                or target.get("owner_id")
            )
            == (
                json.loads(anchor.get("flickr_current_owner_json") or "{}").get("nsid")
                or anchor.get("owner_id")
            )
            == row["owner_id"]
        )
        for source, field in [(target, "target_capture_time"), (anchor, "anchor_capture_time")]:
            dates = json.loads(source.get("flickr_current_dates_json") or "{}")
            assert str(dates.get("takenunknown")) == "0"
            assert str(dates.get("takengranularity")) == "0"
            assert datetime.fromisoformat(row[field]) == datetime.fromisoformat(dates["taken"])
        minutes = (
            datetime.fromisoformat(row["target_capture_time"])
            - datetime.fromisoformat(row["anchor_capture_time"])
        ).total_seconds() / 60
        assert abs(minutes - row["minutes_anchor_before_target"]) < 1e-9
        assert abs(minutes) <= 1440
        if row["time_window"] == "within_1_hour":
            assert abs(minutes) <= 60
        assert row["relation"] == (
            "earlier" if minutes > 0 else "later" if minutes < 0 else "same_time"
        )
        assert not (row["anchor_latitude"] == 0 and row["anchor_longitude"] == 0)
    assert (
        temporal.filter(pl.col("time_window") == "within_1_hour")["flickr_photo_id"].n_unique()
        == manifest["summary"]["images_with_geotagged_neighbor_within_1_hour"]
    )
    assert (
        temporal.filter(
            (pl.col("time_window") == "within_1_hour") & (pl.col("relation") == "earlier")
        )["flickr_photo_id"].n_unique()
        == manifest["summary"]["images_with_geotagged_neighbor_before_within_1_hour"]
    )
    assert sum(manifest["summary"]["mutually_exclusive_status_counts"].values()) == original.height
    assert not evidence.filter(
        pl.col("capture_locality_candidate")
        & pl.col("matched_text").is_in(["IMG", "DSC", "and", "was", "has", "National Park"])
    ).height
    assert manifest["summary"]["cached_comments_checked"] == sum(
        len(json.loads(r.get("flickr_comments_json") or "[]")) for r in original.to_dicts()
    )
    before = temporal.filter(
        (pl.col("time_window") == "within_1_hour") & (pl.col("relation") == "earlier")
    )
    after = temporal.filter(
        (pl.col("time_window") == "within_1_hour") & (pl.col("relation") == "later")
    )
    before.write_csv(root / "hour_before_neighbors.csv")
    after.write_csv(root / "hour_after_neighbors.csv")
    priority = images.filter(
        pl.col("provider_latitude").is_not_null()
        | pl.col("coordinate_machine_tags_json").is_not_null()
        | (pl.col("text_coordinate_clues_json") != "[]")
        | (pl.col("named_locality_candidates_json") != "[]")
        | (pl.col("geotagged_neighbors_within_1_hour") > 0)
    )
    priority.write_csv(root / "priority_location_clues.csv")
    receipt = {
        "validated": True,
        "source_images": original.height,
        "comments_checked": manifest["summary"]["cached_comments_checked"],
        "all_source_ids_exactly_once": True,
        "evidence_ids_unique": True,
        "csv_parquet_roundtrips_exact": True,
        "all_temporal_links_same_owner": True,
        "all_time_deltas_and_directions_verified": True,
        "temporal_timestamps_match_original_capture_fields": True,
        "summary_coordinate_evidence_has_no_duplicate_entries": True,
        "no_self_photo_anchors": True,
        "all_inferred_target_coordinates_unassigned": True,
        "priority_review_images": priority.height,
        "before_one_hour_images": before["flickr_photo_id"].n_unique(),
        "after_one_hour_images": after["flickr_photo_id"].n_unique(),
        "output_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.iterdir()
            if p.suffix in [".csv", ".parquet"] and not p.name.startswith("input_")
        },
    }
    (root / "validation_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.analysis), indent=2))


if __name__ == "__main__":
    main()
