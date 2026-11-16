"""Offline continent lookup from public Natural Earth map-unit boundaries."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

REGIONS = (
    "North America",
    "South America",
    "Europe",
    "Asia",
    "North Africa",
    "Sub-Saharan Africa",
    "Oceania",
    "Antarctica",
    "Other / offshore",
)


@lru_cache(maxsize=1)
def _polygons():
    return json.loads((Path(__file__).parent / "geography/regions.json").read_text())["polygons"]


def _inside_ring(x, y, ring):
    inside = False
    ax, ay = ring[-1]
    for bx, by in ring:
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
        ax, ay = bx, by
    return inside


def _bbox_distance(x, y, bbox, scale):
    west, south, east, north = bbox
    dx = min(max(west - xx, 0, xx - east) for xx in (x - 360, x, x + 360)) * scale
    dy = max(south - y, 0, y - north)
    return dx * dx + dy * dy


def _edge_distance(x, y, ring, scale):
    distance = math.inf
    ax, ay = ring[-1]
    for bx, by in ring:
        # Wrap near the query, preserving short segments at the date line.
        ux = ((ax - x + 180) % 360 - 180) * scale
        vx = ux + ((bx - ax + 180) % 360 - 180) * scale
        uy, vy = ay - y, by - y
        dx, dy = vx - ux, vy - uy
        denominator = dx * dx + dy * dy
        t = min(1, max(0, -(ux * dx + uy * dy) / denominator)) if denominator else 0
        distance = min(distance, (ux + t * dx) ** 2 + (uy + t * dy) ** 2)
        ax, ay = bx, by
    return distance


@lru_cache(maxsize=100_000)
def region_for(latitude: float, longitude: float) -> str:
    """Match land first; snap coastal/island gaps up to roughly 200 km to land."""
    polygons = _polygons()
    for polygon in polygons:
        west, south, east, north = polygon["bbox"]
        if west <= longitude <= east and south <= latitude <= north:
            rings = polygon["rings"]
            if _inside_ring(longitude, latitude, rings[0]) and not any(
                _inside_ring(longitude, latitude, hole) for hole in rings[1:]
            ):
                return polygon["region"]
    scale = max(0.01, math.cos(math.radians(latitude)))
    best, region = (200 / 111.2) ** 2, "Other / offshore"
    candidates = sorted(
        ((_bbox_distance(longitude, latitude, p["bbox"], scale), i) for i, p in enumerate(polygons))
    )
    for lower_bound, index in candidates:
        if lower_bound > best:
            break
        polygon = polygons[index]
        distance = min(
            _edge_distance(longitude, latitude, ring, scale) for ring in polygon["rings"]
        )
        if distance < best:
            best, region = distance, polygon["region"]
    return region
