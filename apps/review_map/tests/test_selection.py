"""Selection and export invariants using synthetic observations only."""

import csv
import io

import pytest

from apps.review_map.core import grid_cell, map_cells, parse_snapshot, selected_csv
from apps.review_map.tests.test_map import record, snapshot


def rows(body):
    return list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))


def test_export_uses_exact_click_time_selection_and_four_requested_columns():
    data = parse_snapshot(
        snapshot(
            record(
                "a",
                bioclip_label="Synthetic alpha",
                fallback_url="https://images.example.invalid/full-a",
            ),
            record("b", bioclip_label="Synthetic beta"),
        )
    )
    result = rows(selected_csv(data, ["a"]))
    assert len(result) == 1
    assert list(result[0]) == ["image_url", "date", "geotag", "bioclip_label"]
    _, lat, lon = grid_cell(data.photos[0].latitude, data.photos[0].longitude)
    assert result[0] == {
        "image_url": "https://images.example.invalid/full-a",
        "date": "2010-03-04",
        "geotag": f"{lat:.6f}, {lon:.6f}",
        "bioclip_label": "Synthetic alpha",
    }
    assert len(rows(selected_csv(data, ["b", "a"]))) == 2
    assert rows(selected_csv(data, [])) == []
    assert b"opaque" not in selected_csv(data, ["a"])


def test_filtered_export_cannot_include_images_outside_visible_date_range():
    data = parse_snapshot(snapshot(record("a"), record("b", captured_at="2020-01-01")))
    assert len(rows(selected_csv(data, ["b"], (2020, 2021)))) == 1
    assert {p["key"] for c in map_cells(data, (2020, 2021)) for p in c["photos"]} == {"b"}
    with pytest.raises(ValueError):
        selected_csv(data, ["a"], (2020, 2021))


@pytest.mark.parametrize("keys", [["missing"], ["a", "a"], None, "a", [{}]])
def test_malformed_selection_fails_closed(keys):
    with pytest.raises(ValueError):
        selected_csv(parse_snapshot(snapshot(record("a"))), keys)


@pytest.mark.parametrize(
    "granularity,expected", [("0", "2010-03-04"), ("4", "2010-03"), ("6", "2010")]
)
def test_csv_preserves_date_precision(granularity, expected):
    data = parse_snapshot(snapshot(record("a", taken_granularity=granularity)))
    assert rows(selected_csv(data, ["a"]))[0]["date"] == expected


def test_csv_date_fallback_and_missing_model_label_are_explicit():
    data = parse_snapshot(snapshot(record("a", taken_unknown=True)))
    result = rows(selected_csv(data, ["a"]))[0]
    assert result["date"] == "2011-01-02"
    assert result["bioclip_label"] == ""


def test_model_labels_are_private_until_export_and_formulas_are_escaped():
    data = parse_snapshot(snapshot(record("a", bioclip_label="=synthetic()")))
    assert "synthetic" not in str(map_cells(data))
    assert rows(selected_csv(data, ["a"]))[0]["bioclip_label"] == "'=synthetic()"


@pytest.mark.parametrize(
    "top10,top5,expected",
    [
        ("Synthetic alpha", "Synthetic beta", "Synthetic alpha"),
        (None, "Synthetic beta", "Synthetic beta"),
        (None, None, ""),
    ],
)
def test_snapshot_uses_actual_bioclip_top1_with_legacy_top5_fallback(top10, top5, expected):
    from tools.prepare_review_map import make_snapshot

    item = {
        "image_id": "synthetic",
        "source_provider": "synthetic",
        "image_url": "https://images.example.invalid/full",
        "geotag": {"latitude": -33, "longitude": 151},
        "model_top10": top10,
        "model_top5": top5,
    }
    exported = make_snapshot([item], {}, "Synthetic map")
    assert parse_snapshot(exported).photos[0].bioclip_label == expected
