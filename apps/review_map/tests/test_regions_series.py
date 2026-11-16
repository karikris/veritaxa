"""Geographic grouping and series counts use synthetic observations."""

import json

import pytest

from apps.review_map.core import map_cells, parse_snapshot, selected_csv, selection_catalog
from apps.review_map.regions import REGIONS, region_for
from apps.review_map.tests.test_map import record, snapshot
from apps.review_map.tests.test_selection import rows


@pytest.mark.parametrize(
    "latitude,longitude,expected",
    [
        (30.04, 31.23, "North Africa"),
        (15.5, 32.56, "North Africa"),
        (4.85, 31.58, "Sub-Saharan Africa"),
        (-18.9, 47.5, "Sub-Saharan Africa"),
        (48.86, 2.35, "Europe"),
        (35.68, 139.76, "Asia"),
        (40.71, -74.01, "North America"),
        (21.3, -157.85, "North America"),
        (4.9, -52.3, "South America"),
        (-33.87, 151.21, "Oceania"),
        (-18.14, 178.44, "Oceania"),
        (-77.85, 166.67, "Antarctica"),
        (0, -140, "Other / offshore"),
    ],
)
def test_continent_lookup_and_african_split(latitude, longitude, expected):
    assert region_for(latitude, longitude) == expected


def test_series_normalisation_changes_bubble_size_without_losing_csv_images():
    data = parse_snapshot(
        snapshot(
            record("a", captured_at="2010-03-04 10:00:00"),
            record("b", captured_at="2010-03-04 13:00:00", longitude=151.20991),
            record("c", captured_at="2010-03-05 10:00:00"),
        )
    )
    cell = map_cells(data)[0]
    assert cell["count"] == 3
    assert cell["series_count"] == 2
    assert cell["radius"] == pytest.approx(6 * 2**0.5)
    assert len(rows(selected_csv(data, ["a", "b", "c"]))) == 3
    assert len({p["series"] for p in cell["photos"]}) == 2


def test_equal_dates_at_different_locations_do_not_merge():
    data = parse_snapshot(snapshot(record("a"), record("b", latitude=20, longitude=30)))
    assert len(map_cells(data)) == 2
    assert all(c["series_count"] == 1 for c in map_cells(data))


def test_partial_and_missing_dates_do_not_collapse_unrelated_series():
    data = parse_snapshot(
        snapshot(
            record("a", taken_granularity="4"),
            record("b", taken_granularity="4"),
            record("c", taken_granularity="6"),
            record("d", captured_at=None, uploaded_at=None),
            record("e", captured_at=None, uploaded_at=None),
        )
    )
    assert map_cells(data)[0]["series_count"] == 5


def test_global_catalog_includes_dates_outside_map_and_only_coarsened_selection_metadata():
    data = parse_snapshot(snapshot(record("a", captured_at="1999-01-01"), record("b")))
    assert sum(c["count"] for c in map_cells(data, (2004, 2026))) == 1
    catalog = selection_catalog(data)
    assert {p["key"] for p in catalog} == {"a", "b"}
    assert all(set(p) == {"key", "region", "label", "cell"} for p in catalog)
    assert catalog[0]["cell"] == catalog[1]["cell"]
    assert all(p["region"] in REGIONS for p in catalog)
    assert "images.example.invalid" not in json.dumps(catalog)
    assert "151.2099" not in json.dumps(catalog)
    assert len(rows(selected_csv(data, ["a", "b"]))) == 2


def test_filter_labels_match_csv_top1_values_including_missing_labels():
    data = parse_snapshot(
        snapshot(
            record("a", bioclip_label="Synthetic alpha"),
            record("b", bioclip_label="Synthetic beta"),
            record("c", bioclip_label=""),
        )
    )
    catalog = selection_catalog(data)
    assert {p["label"] for p in catalog} == {"Synthetic alpha", "Synthetic beta", ""}
    exported = rows(selected_csv(data, [p["key"] for p in catalog]))
    assert [p["label"] for p in catalog] == [row["bioclip_label"] for row in exported]
