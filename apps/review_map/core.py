"""Validated map records, photo dates and a metric display grid."""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from urllib.parse import urlsplit

from pyproj import Transformer

GRID_METRES = 10_000


class SnapshotError(ValueError):
    """A snapshot cannot be safely or completely displayed."""


@dataclass(frozen=True)
class Photo:
    key: str
    latitude: float
    longitude: float
    image_url: str
    fallback_url: str | None
    photo_date: date | None
    date_label: str
    export_date: str
    bioclip_label: str


@dataclass(frozen=True)
class Snapshot:
    title: str
    revision: str
    photos: tuple[Photo, ...]

    @property
    def date_bounds(self) -> tuple[date | None, date | None]:
        dates = [p.photo_date for p in self.photos if p.photo_date]
        return (min(dates), max(dates)) if dates else (None, None)


def _date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
    return parsed if date(1800, 1, 1) <= parsed <= datetime.now(UTC).date() else None


def _resolved_date(record: dict) -> tuple[date | None, str, str]:
    """Keep month/year precision; unreliable capture dates use the upload date."""
    taken = _date(record.get("captured_at"))
    granularity = str(record.get("taken_granularity", "0"))
    if taken and not record.get("taken_unknown", False) and granularity in {"0", "4", "6"}:
        if granularity == "4":
            return taken.replace(day=1), taken.strftime("%b %Y"), taken.strftime("%Y-%m")
        if granularity == "6":
            return taken.replace(month=1, day=1), str(taken.year), str(taken.year)
        return taken, f"{taken.day} {taken:%b %Y}", taken.isoformat()
    uploaded = _date(record.get("uploaded_at"))
    return (
        (uploaded, f"{uploaded.day} {uploaded:%b %Y}", uploaded.isoformat())
        if uploaded
        else (None, "Date unavailable", "")
    )


def display_date(record: dict) -> tuple[date | None, str]:
    value, label, _ = _resolved_date(record)
    return value, label


def _image_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise SnapshotError("Invalid image reference.")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SnapshotError("Images require an HTTPS reference.")
    return value


def parse_snapshot(payload: object) -> Snapshot:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SnapshotError("Unsupported map snapshot.")
    records = payload.get("images")
    if not isinstance(records, list) or not 0 < len(records) <= 100_000:
        raise SnapshotError("Map snapshot has no usable images.")
    if payload.get("image_count") != len(records):
        raise SnapshotError("Map snapshot image count does not match its records.")
    seen, photos = set(), []
    for record in records:
        if not isinstance(record, dict):
            raise SnapshotError("Invalid map record.")
        key = record.get("key")
        if not isinstance(key, str) or not key or len(key) > 128 or key in seen:
            raise SnapshotError("Duplicate or invalid map record.")
        seen.add(key)
        lat, lon = record.get("latitude"), record.get("longitude")
        if (
            isinstance(lat, bool)
            or isinstance(lon, bool)
            or not isinstance(lat, (int, float))
            or not isinstance(lon, (int, float))
            or not math.isfinite(lat)
            or not math.isfinite(lon)
            or not -86 <= lat <= 86
            or not -180 <= lon <= 180
            or (lat, lon) == (0, 0)
        ):
            raise SnapshotError("A map record has invalid coordinates.")
        photo_date, label, export_date = _resolved_date(record)
        model_label = record.get("bioclip_label") or ""
        if (
            not isinstance(model_label, str)
            or len(model_label) > 500
            or any(ord(c) < 32 for c in model_label)
        ):
            raise SnapshotError("Invalid model label.")
        fallback = record.get("fallback_url")
        photos.append(
            Photo(
                key,
                float(lat),
                float(lon),
                _image_url(record.get("image_url")),
                _image_url(fallback) if fallback else None,
                photo_date,
                label,
                export_date,
                model_label,
            )
        )
    title, revision = payload.get("title"), payload.get("revision")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise SnapshotError("Missing map title.")
    if not isinstance(revision, str) or not revision or len(revision) > 128:
        raise SnapshotError("Missing map revision.")
    return Snapshot(title, revision, tuple(photos))


@lru_cache(maxsize=1)
def _transforms():
    return (
        Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True),
        Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True),
    )


def grid_cell(latitude: float, longitude: float) -> tuple[str, float, float]:
    """Return a fixed 100 km² display cell and its WGS84 centre."""
    forward, reverse = _transforms()
    x, y = forward.transform(longitude, latitude)
    ix, iy = math.floor(x / GRID_METRES), math.floor(y / GRID_METRES)
    lon, lat = reverse.transform((ix + 0.5) * GRID_METRES, (iy + 0.5) * GRID_METRES)
    return f"{ix}:{iy}", lat, lon


def date_colour(value: date | None, bounds: tuple[date | None, date | None]) -> str:
    oldest, newest = bounds
    if value is None or oldest is None or newest is None:
        return "#94a3b8"
    fraction = (value - oldest).days / max((newest - oldest).days, 1)
    fraction = min(1.0, max(0.0, fraction)) if oldest != newest else 0.5
    blue, red = (37, 99, 235), (239, 68, 68)
    rgb = [round(a + fraction * (b - a)) for a, b in zip(blue, red, strict=True)]
    return "#" + "".join(f"{value:02x}" for value in rgb)


def visible_photos(snapshot: Snapshot, years: tuple[int, int] | None = None) -> tuple[Photo, ...]:
    return tuple(
        photo
        for photo in snapshot.photos
        if not years or not photo.photo_date or years[0] <= photo.photo_date.year <= years[1]
    )


def selected_csv(
    snapshot: Snapshot, keys: list[str], years: tuple[int, int] | None = None
) -> bytes:
    """Export exactly the requested visible selection; never silently broaden it."""
    allowed = {photo.key: photo for photo in visible_photos(snapshot, years)}
    if (
        not isinstance(keys, list)
        or len(keys) > len(allowed)
        or any(not isinstance(key, str) or key not in allowed for key in keys)
        or len(set(keys)) != len(keys)
    ):
        raise ValueError("The selection changed. Please download again.")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["image_url", "date", "geotag", "bioclip_label"])
    for key in keys:
        photo = allowed[key]
        _, latitude, longitude = grid_cell(photo.latitude, photo.longitude)
        label = photo.bioclip_label
        if label.lstrip().startswith(("=", "+", "-", "@")):
            label = "'" + label
        writer.writerow(
            [
                photo.fallback_url or photo.image_url,
                photo.export_date,
                f"{latitude:.6f}, {longitude:.6f}",
                label,
            ]
        )
    return output.getvalue().encode("utf-8-sig")


def map_cells(snapshot: Snapshot, years: tuple[int, int] | None = None) -> list[dict]:
    """Only coarsened coordinates and opaque keys leave the Python server."""
    groups: dict[str, list[Photo]] = defaultdict(list)
    centres = {}
    for photo in visible_photos(snapshot, years):
        key, lat, lon = grid_cell(photo.latitude, photo.longitude)
        groups[key].append(photo)
        centres[key] = lat, lon
    cells = []
    bounds = snapshot.date_bounds
    for key, photos in sorted(groups.items()):
        photos.sort(key=lambda p: (p.photo_date or date.min, p.key), reverse=True)
        lat, lon = centres[key]
        cells.append(
            {
                "key": key,
                "latitude": lat,
                "longitude": lon,
                "count": len(photos),
                "radius": min(38, 6 * math.sqrt(len(photos))),
                "colour": date_colour(photos[0].photo_date, bounds),
                "photos": [
                    {
                        "key": p.key,
                        "date": p.date_label,
                        "colour": date_colour(p.photo_date, bounds),
                    }
                    for p in photos
                ],
            }
        )
    return cells
