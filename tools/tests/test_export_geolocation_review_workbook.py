import json
import zipfile

import polars as pl
import pytest

from tools.export_geolocation_review_workbook import GROUPS, build_records, export_workbook


@pytest.fixture
def inputs():
    key = "target_scientific_name:Papilio demoleus"
    metadata, clues = [], []
    for index, state in enumerate(
        [
            "named_capture_locality_candidate",
            "text_location_clues_require_review",
            "owner_profile_only_not_photo_location",
            "no_supported_location_clue_found",
            "no_supported_location_clue_found",
        ]
    ):
        positive = index < 4
        review = {"reviewer_name": "Observer A", "result": key if positive else "adult_butterfly"}
        metadata.append(
            {
                "flickr_photo_id": f"00{index}",
                "owner_id": "synthetic-owner",
                "photo_page_url": f"https://example.test/photo/{index}",
                "image_url": f"https://example.test/image/{index}.jpg",
                "flickr_current_title": "=1+1" if index == 0 else f"Synthetic {index}",
                "first_round_result_counts_json": json.dumps({review["result"]: 1}),
                "first_round_reviews_json": json.dumps([review]),
                "first_round_has_conflicting_reviews": False,
                "first_round_unanimous_result": review["result"],
                "source_comments": "🦋" * 17000 if index == 0 else "Original metadata",
            }
        )
        clues.append(
            {
                "flickr_photo_id": f"00{index}",
                "owner_id": "synthetic-owner",
                "photo_page_url": f"https://example.test/photo/{index}",
                "location_clue_status": state,
                "provider_latitude": None,
                "coordinate_machine_tags_json": None,
                "text_coordinate_clues_json": "[]",
                "named_locality_candidates_json": json.dumps(
                    [{"name": "Paris", "country_name": "France"}]
                )
                if index == 0
                else "[]",
                "geotagged_neighbors_within_1_hour": 0,
                "closest_geotagged_neighbor_json": None,
                "owner_profile_location": "France" if index == 2 else None,
                "has_saved_human_review": True,
                "human_majority_label": review["result"],
                "title": "Repeated title alias",
            }
        )
    return pl.DataFrame(metadata), pl.DataFrame(clues)


def test_groups_are_disjoint_and_retain_all_original_metadata(inputs):
    metadata, clues = inputs
    records, columns = build_records(metadata, clues)
    assert len(records) == 4
    assert [r["workbook_location_group"] for r in records] == list(GROUPS)
    assert len(columns) == len(set(columns))
    assert set(metadata.columns) <= set(columns)
    assert columns.count("owner_id") == 1 and columns.count("photo_page_url") == 1
    assert "title" not in columns
    for original, record in zip(metadata.to_dicts()[:4], records, strict=True):
        assert all(record[k] == v for k, v in original.items())


def test_workbook_keeps_literal_strings_long_text_and_four_ordered_tabs(tmp_path, inputs):
    metadata, clues = inputs
    source, geo, output = (
        tmp_path / "source.parquet",
        tmp_path / "clues.parquet",
        tmp_path / "out.xlsx",
    )
    metadata.write_parquet(source)
    clues.write_parquet(geo)
    receipt = export_workbook(source, geo, output)
    assert receipt["images"] == 4
    assert list(receipt["sheets"].values()) == [1, 1, 1, 1]
    assert receipt["all_cell_values_verified"] and receipt["all_images_exactly_once"]
    assert receipt["excel_columns"] > receipt["source_columns"]
    assert "source_comments" in receipt["continuations"]
    with zipfile.ZipFile(output) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml").decode()
        assert "=1+1" in xml
        assert "<f>" not in xml
        assert "<hyperlink " in xml


def test_missing_geolocation_record_fails_instead_of_dropping_image(inputs):
    metadata, clues = inputs
    with pytest.raises(ValueError, match="Missing location analysis"):
        build_records(metadata, clues.filter(pl.col("flickr_photo_id") != "000"))


def test_duplicate_ids_cannot_expand_workbook_join(inputs):
    metadata, clues = inputs
    with pytest.raises(ValueError, match="unique"):
        build_records(metadata, pl.concat([clues, clues.head(1)]))
