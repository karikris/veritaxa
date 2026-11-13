import json
import sqlite3
import zipfile
from datetime import datetime

import polars as pl
import pytest

from tools.analyse_flickr_geolocation import (
    Gazetteer,
    capture_time,
    coordinate_tags,
    evidence_for_unit,
    map_coordinates,
    relative_clues,
    temporal_neighbors,
    text_coordinates,
    valid_coordinates,
    visible,
)
from tools.text_extraction import country_context, deduplicate_evidence
from tools.text_extraction.evidence import OUTPUT_SCHEMAS, safe_frame
from tools.text_extraction.exploration.validate_outputs import validate
from tools.text_extraction.pipeline import analyse


@pytest.fixture
def gazetteer(tmp_path):
    countries = []
    for code, name, gid in [
        ("JP", "Japan", "1"),
        ("IN", "India", "2"),
        ("FR", "France", "3"),
        ("US", "United States", "4"),
        ("GB", "United Kingdom", "5"),
        ("LR", "Liberia", "6"),
        ("CR", "Costa Rica", "7"),
    ]:
        row = [""] * 19
        row[0] = code
        row[4] = name
        row[7] = "1000"
        row[16] = gid
        countries.append("\t".join(row))
    (tmp_path / "countryInfo.txt").write_text("\n".join(countries))
    (tmp_path / "admin1CodesASCII.txt").write_text("")
    cities = []
    for gid, name, country in [
        ("10", "Tokyo", "JP"),
        ("11", "Paris", "FR"),
        ("12", "Paris", "US"),
        ("13", "Liberia", "CR"),
    ]:
        row = [""] * 19
        row[0] = gid
        row[1] = row[2] = name
        row[4] = "35.6"
        row[5] = "139.7"
        row[8] = country
        row[14] = "1000"
        cities.append("\t".join(row))
    with zipfile.ZipFile(tmp_path / "cities1000.zip", "w") as archive:
        archive.writestr("cities1000.txt", "\n".join(cities))
    return Gazetteer(tmp_path)


def test_explicit_locality_resolves_city_using_country_context(gazetteer):
    unit = {
        "text": "Photographed at Paris, France.",
        "source": "description",
        "author_is_owner": True,
    }
    clues = evidence_for_unit(unit, gazetteer, set())
    city = next(c for c in clues if c["matched_text"] == "Paris")
    assert city["capture_locality_candidate"]
    assert [p["country"] for p in city["candidates"]] == ["FR"]
    assert "gazetteer_center_not_photo_coordinate" in city["flags"]


def test_ambiguous_city_is_not_promoted_to_resolved_location(gazetteer):
    clues = evidence_for_unit(
        {"text": "Paris", "source": "title", "author_is_owner": True}, gazetteer, set()
    )
    assert clues[0]["candidate_count"] == 2
    assert not clues[0]["capture_locality_candidate"]


@pytest.mark.parametrize(
    "text,source,kind",
    [
        ("Greetings from Tokyo!", "comment", "greeting_or_group_place"),
        ("Was this taken in Tokyo?", "comment", "location_question"),
        ("This species is native to India.", "description", "distribution_place"),
        ("Tokyo, Japan", "owner_profile", "owner_profile_place"),
    ],
)
def test_non_capture_place_contexts_remain_separate(gazetteer, text, source, kind):
    clues = evidence_for_unit(
        {"text": text, "source": source, "author_is_owner": False}, gazetteer, set()
    )
    assert clues and all(c["kind"] == kind for c in clues)
    assert not any(c["capture_locality_candidate"] for c in clues)


def test_place_matcher_respects_token_boundaries(gazetteer):
    assert list(gazetteer.find("Tokyoite Indiana")) == []
    assert len(list(gazetteer.find("Tokyo, Japan"))) == 2


def test_city_country_homonym_uses_other_photo_country_evidence(gazetteer):
    clues = evidence_for_unit(
        {"text": "Liberia", "source": "tag", "author_is_owner": True}, gazetteer, {"CR"}
    )
    assert clues[0]["candidates"][0]["country"] == "CR"
    assert clues[0]["candidates"][0]["level"] == "settlement"


def test_species_range_language_is_not_a_capture_locality(gazetteer):
    clues = evidence_for_unit(
        {
            "text": "A medium-sized species of butterfly found in India.",
            "source": "description",
            "author_is_owner": True,
        },
        gazetteer,
        set(),
    )
    assert not any(c["capture_locality_candidate"] for c in clues)


@pytest.mark.parametrize(
    "point,expected",
    [((0, 0), None), ((0, 120), (0.0, 120.0)), ((91, 1), None), ((float("nan"), 1), None)],
)
def test_coordinate_checks_preserve_equator_and_reject_placeholders(point, expected):
    assert valid_coordinates(*point) == expected


def target(taken="2020-01-01 12:00:00", unknown=0, granularity=0):
    return {
        "flickr_photo_id": "target",
        "flickr_current_dates_json": json.dumps(
            {"taken": taken, "takenunknown": unknown, "takengranularity": granularity}
        ),
    }


@pytest.mark.parametrize(
    "row",
    [
        target(unknown=1),
        target(granularity=4),
        target(taken="2020-01-01 00:00:00"),
        target(taken=None),
    ],
)
def test_unknown_coarse_or_midnight_time_cannot_support_hourly_neighbor(row):
    assert capture_time(row)[0] is None


def test_hour_prior_and_hour_after_keep_direction_and_avoid_self_matches():
    anchors = [
        {"photo_id": "before", "date": datetime(2020, 1, 1, 11, 0)},
        {"photo_id": "after", "date": datetime(2020, 1, 1, 13, 0)},
        {"photo_id": "target", "date": datetime(2020, 1, 1, 12, 0)},
        {"photo_id": "far", "date": datetime(2020, 1, 3, 12, 0)},
    ]
    matches, basis = temporal_neighbors(target(), anchors)
    assert {
        (r["photo_id"], r["minutes_before_target"], r["relation"], r["time_window"])
        for r in matches
    } == {("before", 60.0, "earlier", "within_1_hour"), ("after", -60.0, "later", "within_1_hour")}
    assert "timezone_unverified" in basis


def test_relative_hour_phrase_does_not_assume_comment_time_is_capture_time():
    clues = relative_clues(
        {"text": "I was at Tokyo an hour prior to taking the photo.", "source": "comment"}
    )
    assert clues[0]["minutes"] == 60
    assert clues[0]["direction"] == "before"
    assert clues[0]["reference_basis"] == "comment_narrative_reference_unresolved"


def test_machine_coordinate_pair_requires_consistent_lat_and_lon():
    assert coordinate_tags({"machine_tags": 'geo:lat="12.25" geo:lon="77.50"'}) == (12.25, 77.5)
    assert coordinate_tags({"machine_tags": "geo:lat=12.25 geo:lat=20 geo:lon=77.5"}) is None


def test_raw_tags_preserve_decimal_point_and_western_hemisphere_sign():
    row = {
        "machine_tags": "geo:lat=44206450 geo:lon=85748892",
        "flickr_current_tags_json": json.dumps(
            {
                "tag": [
                    {"raw": "geo:lat=44.206450", "_content": "geo:lat=44206450"},
                    {"raw": "geo:lon=-85.748892", "_content": "geo:lon=85748892"},
                ]
            }
        ),
    }
    assert coordinate_tags(row) == (44.20645, -85.748892)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("latitude: 44.25, longitude: -85.75", (44.25, -85.75)),
        ("44.25 N, 85.75 W", (44.25, -85.75)),
        ("""44°15'0"N 85°45'0"W""", (44.25, -85.75)),
    ],
)
def test_explicit_coordinate_text_formats(text, expected):
    clues = list(text_coordinates(text))
    assert len(clues) == 1 and clues[0][2] == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://maps.google.com/?q=44.25,-85.75", (44.25, -85.75)),
        ("https://www.openstreetmap.org/#map=15/44.25/-85.75", (44.25, -85.75)),
        ("https://example.com/44.25,-85.75", None),
    ],
)
def test_map_centers_are_extracted_as_anchors_only(url, expected):
    assert map_coordinates(url) == expected


def test_html_images_and_profile_links_do_not_create_visible_place_mentions():
    text, links = visible(
        'Great! <img alt="Tokyo" src="x"><a href="https://example.com/Japan">photo</a>'
    )
    assert text == "Great! photo"
    assert links == ["https://example.com/Japan"]


def test_country_context_does_not_self_confirm_country_city_homonym(gazetteer):
    unit = {"source": "tag", "text": "Liberia", "author_is_owner": True}
    assert country_context([unit], gazetteer) == set()
    assert not evidence_for_unit(unit, gazetteer, set())[0]["capture_locality_candidate"]


def test_evidence_deduplication_retains_occurrences_and_original_record():
    record = {
        "flickr_photo_id": "synthetic",
        "source": "description",
        "excerpt": "a repeated locality",
    }
    result = deduplicate_evidence([record, dict(record)])
    assert len(result) == 1 and result[0]["occurrence_count"] == 2
    assert "evidence_id" not in record


def test_conflicting_evidence_payload_cannot_share_supplied_identity():
    with pytest.raises(ValueError, match="Conflicting evidence"):
        deduplicate_evidence(
            [
                {"evidence_id": "same", "excerpt": "one"},
                {"evidence_id": "same", "excerpt": "different"},
            ]
        )


def test_empty_evidence_preserves_typed_headers():
    frame = safe_frame([], OUTPUT_SCHEMAS["location_evidence"])
    assert frame.height == 0
    assert frame.schema["author_is_owner"] == pl.Boolean
    assert frame.schema["evidence_id"] == pl.String


def test_complete_pipeline_handles_no_location_or_temporal_evidence(tmp_path, gazetteer):
    source = tmp_path / "original.parquet"
    geo = tmp_path / "geo.parquet"
    cache = tmp_path / "cache.sqlite"
    pl.DataFrame(
        {"flickr_photo_id": ["synthetic-photo"], "raw_title": ["Unrelated object"]}
    ).write_parquet(source)
    pl.DataFrame(schema={"flickr_photo_id": pl.String}).write_parquet(geo)
    with sqlite3.connect(cache) as connection:
        connection.execute(
            "CREATE TABLE responses(photo_id TEXT,end"
            "point TEXT,status TEXT,payload TEXT,retr"
            "ieved_at TEXT)"
        )
    output = tmp_path / "analysis"
    result = analyse(source, geo, cache, tmp_path, output)
    assert result["summary"]["total_images"] == 1
    assert result["summary"]["evidence_rows"] == 0
    assert pl.read_csv(output / "location_evidence.csv").height == 0
    assert pl.read_csv(output / "relative_time_evidence.csv").height == 0
    assert pl.read_csv(output / "temporal_geotagged_neighbors.csv").height == 0
    assert (
        pl.read_parquet(output / "image_geolocation_clues.parquet")["location_clue_status"].item()
        == "no_supported_location_clue_found"
    )
    assert validate(output)["validated"]
