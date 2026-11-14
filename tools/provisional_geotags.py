"""Deterministic mapping hypotheses from saved clues; never validated occurrences."""

from __future__ import annotations

import heapq
import json
import math

from tools.location_clue_groups import EXCLUDED_KINDS
from tools.text_extraction.coordinates import valid_coordinates

GEOTAG_KEY = "_veritaxa_geotag"
EARTH_KM = 6371.0088


def distance_km(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(min(1, max(0, value))))


def parsed(value):
    return json.loads(value) if isinstance(value, str) and value else value or []


def provisional_tag(payload: dict, resolve_place) -> dict:
    """Rank existing geographic references, preserving ambiguity and reference identity."""
    points = {}
    owner_countries = set()
    usable = [
        e
        for e in payload["evidence"]
        if e.get("source") != "owner_profile" and e.get("kind") not in EXCLUDED_KINDS
    ]
    for evidence in usable:
        if evidence.get("source") == "comment" and evidence.get("author_is_owner") is not True:
            continue
        for candidate in parsed(evidence.get("candidates")):
            if candidate.get("level") == "country" and candidate.get("country"):
                owner_countries.add(candidate["country"])
    context_country = next(iter(owner_countries)) if len(owner_countries) == 1 else None

    for evidence in usable:
        source = evidence.get("source")
        author = evidence.get("author_is_owner")
        is_capture = bool(evidence.get("capture_locality_candidate"))
        coordinate_reference = evidence.get("kind") in {
            "dms_coordinates",
            "labelled_decimal_coordinates",
            "hemisphere_decimal_coordinates",
            "map_link_coordinates",
            "raw_coordinate_machine_tags",
        }
        for candidate in parsed(evidence.get("candidates")):
            resolved = resolve_place(candidate)
            if resolved is None:
                continue
            if (
                context_country
                and resolved.get("country")
                and resolved["country"] != context_country
            ):
                continue
            point = valid_coordinates(resolved.get("latitude"), resolved.get("longitude"))
            if point is None:
                continue
            level = resolved.get("level", "point")
            score = (
                140
                if coordinate_reference
                else 85
                if is_capture
                else (
                    65
                    if source == "comment" and author is True
                    else 60
                    if source == "title"
                    else 55
                    if source == "tag"
                    else 50
                    if source == "description"
                    else 20
                )
            )
            if level == "country":
                score = min(score, 30)
            elif level == "region":
                score -= 8
            if context_country and resolved.get("country") == context_country:
                score += 12
            key = str(resolved.get("geoname_id") or f"{point[0]:.6f},{point[1]:.6f}")
            entry = points.setdefault(
                key,
                {
                    **resolved,
                    "latitude": point[0],
                    "longitude": point[1],
                    "rank_score": score,
                    "sources": set(),
                    "evidence_ids": set(),
                    "excerpts": [],
                    "coordinate_reference": coordinate_reference,
                },
            )
            entry["rank_score"] = max(score, entry["rank_score"])
            entry["coordinate_reference"] |= coordinate_reference
            entry["sources"].add(f"{source}:{author}")
            if evidence.get("evidence_id"):
                entry["evidence_ids"].add(evidence["evidence_id"])
            excerpt = str(evidence.get("excerpt") or evidence.get("matched_text") or "")[:600]
            if excerpt and excerpt not in entry["excerpts"] and len(entry["excerpts"]) < 3:
                entry["excerpts"].append(excerpt)

    ranked = sorted(
        points.values(),
        key=lambda e: (
            -(e["rank_score"] + 4 * min(3, len(e["sources"]) - 1)),
            -len(e["sources"]),
            str(e.get("geoname_id", "")),
            e["latitude"],
            e["longitude"],
        ),
    )
    for candidate in ranked:
        candidate["sources"] = sorted(candidate["sources"])
        candidate["evidence_ids"] = sorted(candidate["evidence_ids"])
    if ranked:
        chosen = ranked[0]
        alternative_distance = max(
            distance_km((chosen["latitude"], chosen["longitude"]), (c["latitude"], c["longitude"]))
            for c in ranked
        )
        flags = ["provisional_not_human_georeferenced"]
        if len(ranked) > 1:
            flags.append("multiple_place_candidates")
        if alternative_distance > 250:
            flags.append("widely_separated_candidates")
        if chosen.get("level") in {"country", "region"}:
            flags.append("coarse_administrative_reference_point")
        if chosen.get("country") is None:
            flags.append("country_not_resolved")
        method = (
            "text_coordinate_reference"
            if chosen["coordinate_reference"]
            else (
                "administrative_reference_point"
                if chosen.get("level") in {"country", "region"}
                else "gazetteer_place_reference"
            )
        )
        return {
            "schema": "veritaxa-geotag-v1",
            "status": "provisional",
            "method": method,
            "latitude": chosen["latitude"],
            "longitude": chosen["longitude"],
            "place_name": chosen.get("name") or "Quoted coordinate reference",
            "country": chosen.get("country"),
            "country_name": chosen.get("country_name"),
            "level": chosen.get("level", "point"),
            "coordinate_uncertainty_m": None,
            "feature_extent_radius_m": chosen.get("feature_extent_radius_m"),
            "primary_clue_group": payload["primary_group"],
            "clue_sha256": payload["content_sha256"],
            "candidate_count": len(ranked),
            "alternative_spread_km": round(alternative_distance, 1),
            "flags": flags,
            "evidence_ids": chosen["evidence_ids"],
            "sources": chosen["sources"],
            "excerpts": chosen["excerpts"],
            "alternatives": [
                {
                    k: c.get(k)
                    for k in [
                        "name",
                        "country",
                        "country_name",
                        "level",
                        "latitude",
                        "longitude",
                        "geoname_id",
                    ]
                }
                for c in ranked[1:11]
            ],
        }

    anchors = sorted(
        payload.get("temporal_reference_evidence") or [],
        key=lambda r: abs(r["minutes_anchor_before_target"]),
    )
    for anchor in anchors:
        point = valid_coordinates(anchor.get("anchor_latitude"), anchor.get("anchor_longitude"))
        if point:
            return {
                "schema": "veritaxa-geotag-v1",
                "status": "provisional",
                "method": "nearby_photo_proxy",
                "latitude": point[0],
                "longitude": point[1],
                "place_name": "Nearby photograph's location",
                "country": None,
                "country_name": None,
                "level": "temporal_proxy",
                "coordinate_uncertainty_m": None,
                "primary_clue_group": payload["primary_group"],
                "clue_sha256": payload["content_sha256"],
                "candidate_count": len(anchors),
                "alternative_spread_km": None,
                "flags": [
                    "provisional_not_human_georeferenced",
                    "other_photo_location_proxy",
                    "travel_distance_unknown",
                ],
                "anchor_photo_id": anchor["anchor_flickr_photo_id"],
                "minutes_anchor_before_target": anchor["minutes_anchor_before_target"],
                "excerpts": [
                    str(
                        anchor.get("anchor_description_excerpt") or anchor.get("anchor_title") or ""
                    )[:600]
                ],
                "alternatives": [],
            }
    return {
        "schema": "veritaxa-geotag-v1",
        "status": "unresolved",
        "method": "no_resolvable_reference",
        "latitude": None,
        "longitude": None,
        "coordinate_uncertainty_m": None,
        "primary_clue_group": payload["primary_group"],
        "clue_sha256": payload["content_sha256"],
        "flags": ["no_supported_mapping_point"],
        "alternatives": [],
        "excerpts": [],
    }


def _xyz(point):
    lat, lon = map(math.radians, point)
    return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)


def location_isolation(points: list[dict], reference_points: list[tuple], k=5):
    """Distance to kth distinct source-coordinate location; diagnostic, not an error label."""
    unique = sorted(set((round(a, 6), round(b, 6)) for a, b in reference_points))

    def tree(values, depth=0):
        if not values:
            return None
        axis = depth % 3
        values.sort(key=lambda v: v[axis])
        mid = len(values) // 2
        return values[mid], axis, tree(values[:mid], depth + 1), tree(values[mid + 1 :], depth + 1)

    root = tree([_xyz(p) for p in unique])
    for point in points:
        if point.get("latitude") is None:
            continue
        query = _xyz((point["latitude"], point["longitude"]))
        heap = []

        def visit(node, query=query, heap=heap):
            if node is None:
                return
            value, axis, left, right = node
            distance = sum((a - b) ** 2 for a, b in zip(value, query, strict=True))
            if distance > 1e-16:
                heapq.heappush(heap, -distance)
                if len(heap) > k:
                    heapq.heappop(heap)
            delta = query[axis] - value[axis]
            visit(left if delta < 0 else right)
            if len(heap) < k or delta * delta < -heap[0]:
                visit(right if delta < 0 else left)

        visit(root)
        point["isolation_km"] = (
            round(2 * EARTH_KM * math.asin(min(1, math.sqrt(-heap[0]) / 2)), 1) if heap else None
        )
