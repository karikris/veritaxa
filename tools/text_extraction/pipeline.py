"""Frozen-input Flickr location-clue analysis; no Flickr API calls."""

import json
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from .common import digest, dump, snippet
from .context import CLOCK, LOCALITY, country_context, evidence_for_unit, relative_clues
from .coordinates import coordinate_tags, map_coordinates, text_coordinates, valid_coordinates
from .evidence import OUTPUT_SCHEMAS, deduplicate_evidence, safe_frame
from .flickr import source_locations, units
from .gazetteer import Gazetteer
from .html_text import visible
from .temporal import capture_time, temporal_neighbors


def snapshot(path, destination):
    if not destination.exists():
        shutil.copyfile(path, destination)
    if digest(path) != digest(destination):
        raise ValueError(f"Input changed since snapshot: {path}; choose a new output directory")
    return pl.read_parquet(destination)


def analyse(source, geotagged_source, cache_path, gazetteer_root, output):
    output.mkdir(parents=True, exist_ok=True)
    source_frame = snapshot(source, output / "input_original.parquet")
    geo_frame = snapshot(geotagged_source, output / "input_geotagged.parquet")
    if not source_frame.height or source_frame["flickr_photo_id"].null_count():
        raise ValueError("Original source requires non-null photo IDs and at least one image")
    if source_frame["flickr_photo_id"].n_unique() != source_frame.height:
        raise ValueError("Duplicate original photo IDs")
    rows, geo_rows = source_frame.to_dicts(), geo_frame.to_dicts()
    geo_ids = {str(r["flickr_photo_id"]) for r in geo_rows}
    ids = {str(r["flickr_photo_id"]) for r in rows}
    public, cache_snapshot = source_locations(cache_path, ids)
    safe_frame(
        cache_snapshot,
        {
            "flickr_photo_id": pl.String,
            "status": pl.String,
            "retrieved_at": pl.String,
            "provider_location_json": pl.String,
        },
    ).write_parquet(output / "provider_location_snapshot.parquet")
    gazetteer = Gazetteer(gazetteer_root)
    print(
        dump(
            {
                "state": "gazetteer_loaded",
                "places": len(gazetteer.places),
                "aliases": len(gazetteer.aliases),
            }
        ),
        flush=True,
    )
    anchors, seen = defaultdict(list), set()
    for row in geo_rows + rows:
        pid = str(row["flickr_photo_id"])
        coordinates = public.get(pid)
        method = "flickr_getInfo_location"
        if not coordinates:
            point = (
                valid_coordinates(row.get("latitude"), row.get("longitude"))
                if pid in geo_ids
                else None
            )
            coordinates = dict(latitude=point[0], longitude=point[1]) if point else None
            method = "flickr_search_geotag"
        if not coordinates:
            point = coordinate_tags(row)
            coordinates = dict(latitude=point[0], longitude=point[1]) if point else None
            method = "explicit_coordinate_machine_tags"
        date, _quality = capture_time(row)
        owner = json.loads(row.get("flickr_current_owner_json") or "{}").get("nsid") or row.get(
            "owner_id"
        )
        if coordinates and date and owner and pid not in seen:
            anchors[owner].append(
                dict(
                    photo_id=pid,
                    date=date,
                    latitude=coordinates["latitude"],
                    longitude=coordinates["longitude"],
                    method=method,
                    page_url=row.get("photo_page_url"),
                    coordinate_accuracy=row.get("geolocation_accuracy_flickr_level"),
                    title=row.get("flickr_current_title") or row.get("raw_title"),
                    description=visible(
                        row.get("flickr_current_description") or row.get("raw_description")
                    )[0][:400],
                )
            )
            seen.add(pid)
    evidence, relative, temporal, summaries = [], [], [], []
    methods = Counter()
    for index, row in enumerate(rows):
        pid = str(row["flickr_photo_id"])
        owner = json.loads(row.get("flickr_current_owner_json") or "{}").get("nsid") or row.get(
            "owner_id"
        )
        photo_units = list(units(row))
        tag_countries = country_context(photo_units, gazetteer)
        photo_evidence, photo_relative = [], []
        for unit in photo_units:
            common = {k: v for k, v in unit.items() if k not in {"text", "links"}}
            for clue in evidence_for_unit(unit, gazetteer, tag_countries):
                photo_evidence.append(dict(flickr_photo_id=pid, **common, **clue))
            if unit["source"] != "owner_profile":
                for clue in relative_clues(unit):
                    photo_relative.append(dict(flickr_photo_id=pid, **common, **clue))
                for match in CLOCK.finditer(unit["text"]):
                    photo_relative.append(
                        dict(
                            flickr_photo_id=pid,
                            **common,
                            expression=match[0],
                            minutes=None,
                            direction=None,
                            reference_basis="clock_time_in_text_timezone_unresolved",
                            excerpt=snippet(unit["text"], match.start(), match.end()),
                        )
                    )
                if not list(gazetteer.find(unit["text"])):
                    for match in LOCALITY.finditer(unit["text"]):
                        photo_evidence.append(
                            dict(
                                flickr_photo_id=pid,
                                **common,
                                kind="unresolved_locality_phrase",
                                matched_text=match[1] or match[2],
                                excerpt=snippet(unit["text"], match.start(), match.end()),
                                candidates=[],
                                candidate_count=0,
                                flags=["uncatalogued_locality_requires_review"],
                                capture_locality_candidate=False,
                            )
                        )
                for kind, raw, point in text_coordinates(unit["text"]):
                    start = unit["text"].find(raw)
                    photo_evidence.append(
                        dict(
                            flickr_photo_id=pid,
                            **common,
                            kind=kind,
                            matched_text=raw,
                            excerpt=snippet(unit["text"], start, start + len(raw)),
                            candidates=[dict(latitude=point[0], longitude=point[1])],
                            candidate_count=1,
                            flags=["text_coordinate_reference_requires_review"],
                            capture_locality_candidate=False,
                        )
                    )
                for url in unit["links"]:
                    point = map_coordinates(url)
                    if point:
                        photo_evidence.append(
                            dict(
                                flickr_photo_id=pid,
                                **common,
                                kind="map_link_coordinates",
                                matched_text=url,
                                excerpt=unit["text"][:350],
                                candidates=[dict(latitude=point[0], longitude=point[1])],
                                candidate_count=1,
                                flags=["map_query_or_center_not_verified_photo_coordinate"],
                                capture_locality_candidate=False,
                            )
                        )
        neighbors, time_quality = temporal_neighbors(row, anchors.get(owner, []))
        photo_temporal = []
        for anchor in neighbors:
            photo_temporal.append(
                dict(
                    flickr_photo_id=pid,
                    owner_id=owner,
                    target_capture_time=json.loads(
                        row.get("flickr_current_dates_json") or "{}"
                    ).get("taken"),
                    anchor_flickr_photo_id=anchor["photo_id"],
                    anchor_capture_time=anchor["date"].isoformat(sep=" "),
                    target_photo_page_url=row.get("photo_page_url"),
                    target_title=row.get("flickr_current_title") or row.get("raw_title"),
                    anchor_title=anchor["title"],
                    anchor_description_excerpt=anchor["description"],
                    anchor_photo_page_url=anchor["page_url"],
                    anchor_latitude=anchor["latitude"],
                    anchor_longitude=anchor["longitude"],
                    anchor_method=anchor["method"],
                    anchor_coordinate_accuracy=anchor["coordinate_accuracy"],
                    minutes_anchor_before_target=anchor["minutes_before_target"],
                    relation=anchor["relation"],
                    time_window=anchor["time_window"],
                    matching_anchor_count=anchor["matching_anchor_count"],
                    time_basis=time_quality,
                    inference_status="temporal_location_clue_only_target_coordinate_unassigned",
                )
            )
        machine = coordinate_tags(row)
        for kind, point in [
            ("public_flickr_coordinates", public.get(pid)),
            (
                "raw_machine_tag_coordinates",
                dict(latitude=machine[0], longitude=machine[1]) if machine else None,
            ),
        ]:
            if point:
                coordinates = dict(latitude=point["latitude"], longitude=point["longitude"])
                photo_evidence.append(
                    dict(
                        flickr_photo_id=pid,
                        source="provider_metadata"
                        if kind == "public_flickr_coordinates"
                        else "raw_machine_tags",
                        field="flickr.photos.getInfo.photo.location"
                        if kind == "public_flickr_coordinates"
                        else "flickr.photos.getInfo.photo.tags.tag.raw",
                        author_is_owner=None,
                        comment_id=None,
                        comment_author=None,
                        comment_created_at=None,
                        kind=kind,
                        matched_text=dump(coordinates),
                        excerpt=dump(point.get("location", coordinates)),
                        candidates=[coordinates],
                        candidate_count=1,
                        flags=["source_coordinate_not_independently_verified"],
                        capture_locality_candidate=False,
                    )
                )
        photo_evidence = deduplicate_evidence(photo_evidence)
        candidates = [e for e in photo_evidence if e["capture_locality_candidate"]]
        text_points = [
            e
            for e in photo_evidence
            if e["kind"]
            in {
                "labelled_decimal_coordinates",
                "hemisphere_decimal_coordinates",
                "dms_coordinates",
                "map_link_coordinates",
            }
        ]
        hour = [n for n in photo_temporal if n["time_window"] == "within_1_hour"]
        photo_text = [
            e
            for e in photo_evidence
            if e["source"] in {"title", "description", "tag", "comment"}
            and e["kind"]
            not in {"greeting_or_group_place", "distribution_place", "location_question"}
        ]
        if pid in public:
            status = "public_flickr_coordinates_recovered"
        elif machine:
            status = "coordinate_machine_tags_require_review"
        elif text_points:
            status = "text_coordinate_references_require_review"
        elif candidates:
            status = "named_capture_locality_candidate"
        elif hour:
            status = "same_owner_geotagged_neighbor_within_1_hour"
        elif photo_text:
            status = "text_location_clues_require_review"
        elif photo_temporal:
            status = "same_owner_geotagged_neighbor_within_24_hours"
        elif photo_relative:
            status = "relative_time_clue_only"
        elif any(e["source"] == "owner_profile" for e in photo_evidence):
            status = "owner_profile_only_not_photo_location"
        else:
            status = "no_supported_location_clue_found"
        methods[status] += 1
        unique_places = {
            p.get("geoname_id"): p
            for e in candidates
            for p in e["candidates"]
            if p.get("geoname_id")
        }
        summaries.append(
            dict(
                flickr_photo_id=pid,
                photo_page_url=row.get("photo_page_url"),
                owner_id=owner,
                title=row.get("flickr_current_title") or row.get("raw_title"),
                capture_time=json.loads(row.get("flickr_current_dates_json") or "{}").get("taken"),
                capture_time_quality=time_quality,
                has_saved_human_review=row.get("has_saved_review"),
                human_majority_label=row.get("first_round_strict_majority_result"),
                location_clue_status=status,
                provider_latitude=public.get(pid, {}).get("latitude"),
                provider_longitude=public.get(pid, {}).get("longitude"),
                provider_accuracy_flickr_level=public.get(pid, {})
                .get("location", {})
                .get("accuracy"),
                coordinate_machine_tags_json=dict(latitude=machine[0], longitude=machine[1])
                if machine
                else None,
                text_coordinate_clues_json=[
                    dict(
                        kind=e["kind"],
                        source=e["source"],
                        field=e["field"],
                        excerpt=e["excerpt"],
                        candidates=e["candidates"],
                    )
                    for e in text_points
                ],
                named_locality_candidates_json=list(unique_places.values()),
                location_evidence_count=len(photo_evidence),
                photo_text_location_evidence_count=len(photo_text),
                owner_comment_location_evidence_count=sum(
                    e["source"] == "comment" and e["author_is_owner"] for e in photo_evidence
                ),
                third_party_comment_location_evidence_count=sum(
                    e["source"] == "comment" and not e["author_is_owner"] for e in photo_evidence
                ),
                owner_profile_location=json.loads(row.get("flickr_current_owner_json") or "{}").get(
                    "location"
                ),
                relative_time_clue_count=len(photo_relative),
                geotagged_neighbors_within_1_hour=len(hour),
                geotagged_neighbor_before_within_1_hour=any(
                    n["relation"] == "earlier" for n in hour
                ),
                geotagged_neighbor_after_within_1_hour=any(n["relation"] == "later" for n in hour),
                closest_geotagged_neighbor_json=min(
                    photo_temporal, key=lambda n: abs(n["minutes_anchor_before_target"])
                )
                if photo_temporal
                else None,
                inferred_target_latitude=None,
                inferred_target_longitude=None,
                review_status="location_not_independently_verified",
            )
        )
        evidence.extend(photo_evidence)
        relative.extend(photo_relative)
        temporal.extend(photo_temporal)
        if (index + 1) % 1000 == 0:
            print(
                dump(
                    {
                        "processed": index + 1,
                        "total": len(rows),
                        "location_evidence": len(evidence),
                        "temporal_links": len(temporal),
                    }
                ),
                flush=True,
            )
    for name, records in [
        ("image_geolocation_clues", summaries),
        ("location_evidence", evidence),
        ("relative_time_evidence", relative),
        ("temporal_geotagged_neighbors", temporal),
    ]:
        frame = safe_frame(records, OUTPUT_SCHEMAS.get(name))
        frame.write_parquet(output / f"{name}.parquet")
        frame.write_csv(output / f"{name}.csv")
    summary = dict(
        total_images=len(rows),
        cached_comments_checked=sum(
            len(json.loads(r.get("flickr_comments_json") or "[]")) for r in rows
        ),
        public_coordinate_images=len(public),
        machine_coordinate_images=sum(bool(r["coordinate_machine_tags_json"]) for r in summaries),
        images_with_named_capture_locality_candidate=sum(
            bool(r["named_locality_candidates_json"]) for r in summaries
        ),
        images_with_photo_text_place_clue=sum(
            r["photo_text_location_evidence_count"] > 0 for r in summaries
        ),
        images_with_owner_comment_place_clue=sum(
            r["owner_comment_location_evidence_count"] > 0 for r in summaries
        ),
        images_with_third_party_comment_place_clue=sum(
            r["third_party_comment_location_evidence_count"] > 0 for r in summaries
        ),
        images_with_relative_time_clue=sum(r["relative_time_clue_count"] > 0 for r in summaries),
        images_with_geotagged_neighbor_within_1_hour=sum(
            r["geotagged_neighbors_within_1_hour"] > 0 for r in summaries
        ),
        images_with_geotagged_neighbor_before_within_1_hour=sum(
            r["geotagged_neighbor_before_within_1_hour"] for r in summaries
        ),
        images_with_geotagged_neighbor_after_within_1_hour=sum(
            r["geotagged_neighbor_after_within_1_hour"] for r in summaries
        ),
        images_with_geotagged_neighbor_within_24_hours=sum(
            r["closest_geotagged_neighbor_json"] is not None for r in summaries
        ),
        images_with_text_or_map_coordinate_clue=len(
            {
                e["flickr_photo_id"]
                for e in evidence
                if e["kind"]
                in {
                    "labelled_decimal_coordinates",
                    "hemisphere_decimal_coordinates",
                    "dms_coordinates",
                    "map_link_coordinates",
                }
            }
        ),
        images_with_travel_timing_expression=len(
            {
                e["flickr_photo_id"]
                for e in relative
                if e.get("narrative_type") == "travel_or_itinerary_timing"
            }
        ),
        images_with_biological_stage_timing_expression=len(
            {
                e["flickr_photo_id"]
                for e in relative
                if e.get("narrative_type") == "biological_stage_timing"
            }
        ),
        images_with_clock_time_text=len(
            {
                e["flickr_photo_id"]
                for e in relative
                if e["reference_basis"] == "clock_time_in_text_timezone_unresolved"
            }
        ),
        mutually_exclusive_status_counts=dict(methods),
        evidence_rows=len(evidence),
        relative_time_rows=len(relative),
        temporal_link_rows=len(temporal),
        geotagged_anchor_images=sum(map(len, anchors.values())),
        flickr_api_calls=0,
    )
    manifest = dict(
        created_at_utc=datetime.now(UTC).isoformat(),
        summary=summary,
        source_sha256={
            str(p): digest(p)
            for p in [
                output / "input_original.parquet",
                output / "input_geotagged.parquet",
                output / "provider_location_snapshot.parquet",
            ]
        },
        gazetteer_sha256={p.name: digest(p) for p in gazetteer_root.iterdir() if p.is_file()},
        code_sha256=digest(Path(__file__)),
        code_files_sha256={p.name: digest(p) for p in Path(__file__).parent.glob("*.py")},
        gazetteer_source="https://download.geonames.org/export/dump/",
        gazetteer_license="CC BY 4.0",
        limitations=[
            (
                "Gazetteer matching is candidate extracti"
                "on, not a trained contextual geocoder. A"
                "mbiguous place names remain unresolved."
            ),
            (
                "Cities under 1000 population and landmar"
                "ks may be absent. Named-place centers ar"
                "e not image coordinates."
            ),
            (
                "Comments can describe the commenter or s"
                "pecies range rather than the photo. Owne"
                "r profile locations are not capture loca"
                "tions."
            ),
            (
                "Recorded same-owner wall-clock times hav"
                "e no verified timezone. Unknown, coarse,"
                " midnight and timezone-aware capture tim"
                "es are excluded from temporal matching."
            ),
            (
                "A geotagged photo taken an hour earlier "
                "or later is a clue, not a location or un"
                "certainty bound for this photo."
            ),
            (
                "No other photos outside the supplied col"
                "lections were fetched. No bulk geocoding"
                " API or Flickr API used."
            ),
            "Inferred target coordinates remain empty pending source/context review.",
        ],
    )
    (output / "analysis_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(dump(summary), flush=True)
    return manifest
