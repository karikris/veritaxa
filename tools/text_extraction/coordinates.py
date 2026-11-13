"""Explicit coordinate syntax; extraction never assigns a target location."""

import json
import math
import re
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

COORD_TAG = re.compile(
    (
        "(?:geo:|geotagged:)?(lat(?:itude)?|lon(?"
        ":gitude)?|lng)\\s*[=:]\\s*[\\\"']?(-?\\d+(?:\\"
        ".\\d+)?)"
    ),
    re.I,
)


COORD_TEXT = re.compile(
    (
        "\\b(?:latitude|lat)\\s*[:=]\\s*(-?\\d{1,2}(?"
        ":\\.\\d+)?)\\s*[,; /]+\\s*(?:longitude|lon|l"
        "ng)\\s*[:=]\\s*(-?\\d{1,3}(?:\\.\\d+)?)"
    ),
    re.I,
)


HEMISPHERE = re.compile(
    r"(?<![\d.])(-?\d{1,2}\.\d{2,})\s*([NS])\s*[,;/ ]+(-?\d{1,3}\.\d{2,})\s*([EW])\b", re.I
)


DMS = re.compile(
    (
        "(\\d{1,2})\\s*[°º]\\s*(\\d{1,2})\\s*['\u2032]\\s*(\\"
        'd{1,2}(?:\\.\\d+)?)\\s*["\u2033]?\\s*([NS])\\s*[,;'
        "/ ]+(\\d{1,3})\\s*[°º]\\s*(\\d{1,2})\\s*['\u2032]\\"
        's*(\\d{1,2}(?:\\.\\d+)?)\\s*["\u2033]?\\s*([EW])'
    ),
    re.I,
)


def valid_coordinates(latitude, longitude):
    try:
        a, b = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if (
        not all(map(math.isfinite, (a, b)))
        or not (-90 <= a <= 90 and -180 <= b <= 180)
        or (a == 0 and b == 0)
    ):
        return None
    return a, b


def coordinate_tags(row):
    tags = json.loads(row.get("flickr_current_tags_json") or "{}").get("tag", [])
    # Prefer raw API values: Flickr's normalized _content strips punctuation,
    # including minus signs and decimal points. Never scale normalized integers.
    texts = [
        "\n".join(str(t.get("raw") or "") for t in tags),
        str(row.get("machine_tags") or ""),
        str(row.get("raw_tags") or ""),
    ]
    for text in texts:
        pairs = defaultdict(set)
        for match in COORD_TAG.finditer(text):
            axis = "lat" if match[1].lower().startswith("lat") else "lon"
            value = float(match[2])
            if abs(value) <= (90 if axis == "lat" else 180):
                pairs[axis].add(value)
        if len(pairs["lat"]) > 1 or len(pairs["lon"]) > 1:
            return None
        if len(pairs["lat"]) == len(pairs["lon"]) == 1:
            return valid_coordinates(next(iter(pairs["lat"])), next(iter(pairs["lon"])))
    return None


def text_coordinates(text):
    for match in COORD_TEXT.finditer(text):
        if point := valid_coordinates(match[1], match[2]):
            yield "labelled_decimal_coordinates", match[0], point
    for match in HEMISPHERE.finditer(text):
        lat = abs(float(match[1])) * (-1 if match[2].upper() == "S" else 1)
        lon = abs(float(match[3])) * (-1 if match[4].upper() == "W" else 1)
        if point := valid_coordinates(lat, lon):
            yield "hemisphere_decimal_coordinates", match[0], point
    for match in DMS.finditer(text):
        if any(float(match[i]) >= 60 for i in [2, 3, 6, 7]):
            continue
        lat = (float(match[1]) + float(match[2]) / 60 + float(match[3]) / 3600) * (
            -1 if match[4].upper() == "S" else 1
        )
        lon = (float(match[5]) + float(match[6]) / 60 + float(match[7]) / 3600) * (
            -1 if match[8].upper() == "W" else 1
        )
        if point := valid_coordinates(lat, lon):
            yield "dms_coordinates", match[0], point


def map_coordinates(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (
        "google." in host or host.endswith("openstreetmap.org") or host.endswith("toolforge.org")
    ):
        return None
    query = parse_qs(parsed.query)
    for latkey, lonkey in [("mlat", "mlon"), ("lat", "lon")]:
        if latkey in query and lonkey in query:
            return valid_coordinates(query[latkey][0], query[lonkey][0])
    for value in [query.get("q", [""])[0], query.get("ll", [""])[0], parsed.path]:
        match = re.search(r"@?(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", value)
        if match and (point := valid_coordinates(match[1], match[2])):
            return point
    match = re.search(r"map=\d+/(-?\d{1,2}(?:\.\d+)?)/(-?\d{1,3}(?:\.\d+)?)", parsed.fragment)
    return valid_coordinates(match[1], match[2]) if match else None
