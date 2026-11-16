from __future__ import annotations

import copy
import io
import json
from datetime import date

import pytest
from PIL import Image

from apps.review_map.core import SnapshotError, date_colour, display_date, map_cells, parse_snapshot
from apps.review_map.images import ImageUnavailable, Thumbnails, allowed_url, make_thumbnail
from apps.review_map.source import load_snapshot
from tools.prepare_review_map import make_snapshot


def record(key="opaque-a", **changes):
    return {
        "key": key,
        "latitude": -33.865143,
        "longitude": 151.2099,
        "image_url": "https://images.example.invalid/preview",
        "captured_at": "2010-03-04 12:00:00",
        "uploaded_at": "2011-01-02T00:00:00Z",
        **changes,
    }


def snapshot(*records):
    return {
        "schema_version": 1,
        "revision": "synthetic-v1",
        "title": "Synthetic photographs",
        "image_count": len(records),
        "images": list(records),
    }


def test_counts_reconcile_and_only_display_cells_leave_server():
    first = record()
    second = record("opaque-b", longitude=151.20991, captured_at="2020-01-01")
    cells = map_cells(parse_snapshot(snapshot(first, second)))
    assert len(cells) == 1
    assert cells[0]["count"] == 2
    assert cells[0]["radius"] > map_cells(parse_snapshot(snapshot(first)))[0]["radius"]
    assert cells[0]["photos"][0] == {"key": "opaque-b", "date": "1 Jan 2020", "colour": "#ef4444"}
    serialized = json.dumps(cells)
    assert first["image_url"] not in serialized
    assert str(first["latitude"]) not in serialized
    assert "coordinate_provenance" not in serialized


@pytest.mark.parametrize(
    "changes",
    [
        {"latitude": 100},
        {"longitude": 181},
        {"latitude": 0, "longitude": 0},
        {"latitude": float("nan")},
        {"latitude": True},
    ],
)
def test_invalid_coordinates_fail_without_silently_losing_images(changes):
    with pytest.raises(SnapshotError):
        parse_snapshot(snapshot(record(**changes)))


def test_duplicate_images_fail_instead_of_inflating_counts():
    with pytest.raises(SnapshotError, match="Duplicate"):
        parse_snapshot(snapshot(record(), record()))


def test_capture_date_fallback_and_partial_date_precision():
    assert display_date(record(captured_at="2999-01-01")) == (date(2011, 1, 2), "2 Jan 2011")
    assert display_date(record(taken_unknown=True)) == (date(2011, 1, 2), "2 Jan 2011")
    assert display_date(record(taken_granularity="4")) == (date(2010, 3, 1), "Mar 2010")
    assert display_date(record(taken_granularity="6")) == (date(2010, 1, 1), "2010")
    assert display_date(record(captured_at=None, uploaded_at=None)) == (None, "Date unavailable")


def test_colours_use_global_date_scale_and_latest_photo_in_cell():
    data = parse_snapshot(
        snapshot(
            record(),
            record("b", captured_at="2020-03-04"),
            record("c", latitude=20, longitude=30, captured_at="2000-03-04"),
        )
    )
    cells = map_cells(data)
    group = next(cell for cell in cells if cell["count"] == 2)
    assert group["colour"] == "#ef4444"
    filtered = map_cells(data, (2010, 2020))
    assert filtered[0]["colour"] == group["colour"]
    assert date_colour(date(2000, 3, 4), data.date_bounds) == "#2563eb"


def test_no_matching_years_produces_an_empty_map():
    assert map_cells(parse_snapshot(snapshot(record())), (2020, 2021)) == []


def test_image_allowlist_rejects_private_hosts_and_redirect_targets():
    host = "live." + "staticflickr.com"
    assert allowed_url(f"https://{host}/synthetic")
    assert not allowed_url("http://127.0.0.1/private")
    assert not allowed_url("https://localhost/private")
    assert not allowed_url(f"https://{host}.example.invalid/private")
    assert not allowed_url(f"https://{host}:8080/private")
    assert not allowed_url(f"https://secret@{host}/private")


def test_thumbnail_is_bounded_and_drops_source_metadata():
    source = Image.new("RGB", (1400, 1000), "green")
    exif = Image.Exif()
    exif[270] = "Synthetic private metadata"
    body = io.BytesIO()
    source.save(body, format="JPEG", exif=exif)
    result = make_thumbnail(body.getvalue())
    with Image.open(io.BytesIO(result)) as image:
        assert image.width <= 640 and image.height <= 480
        assert not image.getexif()
        assert image.format == "WEBP"
    with pytest.raises(ImageUnavailable):
        make_thumbnail(b"not an image")


def test_thumbnail_cache_reuses_download_and_bounds_entries(tmp_path, monkeypatch):
    cache = Thumbnails(tmp_path, max_entries=1)
    source = io.BytesIO()
    Image.new("RGB", (10, 10)).save(source, format="PNG")
    calls = []

    def download(url):
        calls.append(url)
        return source.getvalue()

    monkeypatch.setattr(cache, "_download", download)
    host = "live." + "staticflickr.com"
    one, two = f"https://{host}/one", f"https://{host}/two"
    assert cache.get(one) == cache.get(one)
    assert calls == [one]
    cache.get(two)
    assert len(list(tmp_path.glob("*.webp"))) == 1


def test_private_snapshot_loader_checks_count_and_redacts_errors(tmp_path):
    payload = snapshot(record())
    path = tmp_path / "private.json"
    path.write_text(json.dumps(payload))
    assert len(load_snapshot(str(path), local=True).photos) == 1
    broken = copy.deepcopy(payload)
    broken["image_count"] = 2
    path.write_text(json.dumps(broken))
    with pytest.raises(SnapshotError):
        load_snapshot(str(path), local=True)
    with pytest.raises(SnapshotError) as caught:
        load_snapshot(str(tmp_path / "missing-secret-reference"), local=True)
    assert "missing-secret-reference" not in str(caught.value)


def test_exporter_preserves_private_provenance_without_exporting_reviewer_fields():
    item = {
        "image_id": "synthetic",
        "source_provider": "synthetic",
        "source_record_id": "photo",
        "image_url": "https://images.example.invalid/full",
        "display_url": "https://images.example.invalid/preview",
        "geotag": {"latitude": -33, "longitude": 151, "status": "provisional"},
        "reviewer_email": "synthetic@example.invalid",
    }
    exported = make_snapshot(
        [item], {"photo": {"taken": "2010-03-04", "posted": "1293926400"}}, "Synthetic map"
    )
    parsed = parse_snapshot(exported)
    assert exported["images"][0]["coordinate_provenance"] == "provisional"
    assert "reviewer_email" not in json.dumps(exported)
    assert "source_record_id" not in json.dumps(exported)
    assert len(parsed.photos) == 1


def test_failed_thumbnail_returns_placeholder_without_disclosing_source_url(tmp_path):
    from apps.review_map.images import image_response

    class Unavailable:
        def get(self, _url):
            raise ImageUnavailable("Image unavailable.")

    photo = parse_snapshot(snapshot(record())).photos[0]
    assert image_response(photo, "synthetic-request", Unavailable()) == {
        "token": "synthetic-request",
        "unavailable": True,
    }
