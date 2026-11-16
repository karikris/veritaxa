"""A private live pointer keeps Cloud configuration stable across reviewed snapshots."""

import hashlib
import io
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from apps.review_map.core import SnapshotError
from apps.review_map.source import load_snapshot
from apps.review_map.tests.test_map import record, snapshot
from tools import activate_review_map_snapshot as activation


class Reply(io.BytesIO):
    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def iter_content(self, size):
        while chunk := self.read(size):
            yield chunk


def test_private_pointer_verifies_content_and_does_not_send_rejected_images(monkeypatch):
    child = json.dumps(snapshot(record("kept"))).encode()
    target = "https://project.example.invalid/storage/snapshot?token=synthetic"
    pointer = {
        "schema_version": 2,
        "snapshot_url": target,
        "sha256": hashlib.sha256(child).hexdigest(),
        "revision": "synthetic-v1",
        "image_count": 1,
    }
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return Reply(
            json.dumps(pointer).encode() if urlsplit(url).path.endswith("active") else child
        )

    monkeypatch.setattr("apps.review_map.source.requests.get", get)
    result = load_snapshot(
        "https://project.example.invalid/storage/v1/object/sign/private-map/active?token=synthetic",
        local=False,
    )
    assert [p.key for p in result.photos] == ["kept"]
    assert "_map_cache=" in calls[0]
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["checksum", "host", "count", "revision", "nested"])
def test_invalid_private_pointer_fails_closed_without_exposing_its_signed_url(monkeypatch, change):
    child = json.dumps(snapshot(record())).encode()
    target = "https://project.example.invalid/snapshot?token=private-synthetic-token"
    pointer = {
        "schema_version": 2,
        "snapshot_url": target,
        "sha256": hashlib.sha256(child).hexdigest(),
        "revision": "synthetic-v1",
        "image_count": 1,
    }
    if change == "checksum":
        pointer["sha256"] = "0" * 64
    if change == "host":
        pointer["snapshot_url"] = "https://other.example.invalid/snapshot"
    if change == "count":
        pointer["image_count"] = 2
    if change == "revision":
        pointer["revision"] = "wrong-revision"
    if change == "nested":
        child = json.dumps(pointer).encode()
        pointer["sha256"] = hashlib.sha256(child).hexdigest()

    def get(url, **_):
        return Reply(json.dumps(pointer).encode() if urlsplit(url).path == "/active" else child)

    monkeypatch.setattr("apps.review_map.source.requests.get", get)
    with pytest.raises(SnapshotError) as caught:
        load_snapshot("https://project.example.invalid/active?token=synthetic", local=False)
    assert "private-synthetic-token" not in str(caught.value)


@pytest.mark.parametrize(
    "failure", [None, "public-bucket", "changed-source", "changed-target", "delayed-read"]
)
def test_activation_archives_previous_data_and_replaces_only_the_private_pointer(
    tmp_path, monkeypatch, failure
):
    base = "https://project.example.invalid"
    origin = base + "/storage/v1"
    old = json.dumps(snapshot(record("old"))).encode()
    new = json.dumps(snapshot(record("new"))).encode()
    old_path, new_path = "private-map/snapshots/old.json", "private-map/snapshots/new.json"
    objects = {old_path: old, new_path: new}
    writes = []
    sleeps = []
    stale_reads = 1 if failure == "delayed-read" else 0
    updated = False
    monkeypatch.setattr(activation.time, "sleep", sleeps.append)

    def receipt(path, body):
        return {
            "bucket": "private-map",
            "object_path": path,
            "sha256": hashlib.sha256(body).hexdigest(),
            "signed_url": origin + "/object/sign/" + path + "?token=synthetic",
            "verified_private": True,
            "images": 1,
        }

    channel, target = receipt(old_path, old), receipt(new_path, new)
    if failure == "changed-source":
        channel["sha256"] = "0" * 64
    if failure == "changed-target":
        target["sha256"] = "0" * 64
    monkeypatch.setattr(
        activation, "RestAdmin", lambda _: SimpleNamespace(origin=base, key="synthetic-admin")
    )

    def request(req, timeout):
        nonlocal stale_reads, updated
        assert timeout == 45
        if isinstance(req, str):
            path = urlsplit(req).path.removeprefix("/storage/v1/object/sign/")
            if path == old_path and updated and stale_reads:
                stale_reads -= 1
                return Reply(old)
            return Reply(objects[path])
        path = urlsplit(req.full_url).path.removeprefix("/storage/v1")
        method = req.get_method()
        if path.startswith("/bucket/"):
            return Reply(json.dumps({"public": failure == "public-bucket"}).encode())
        if path.startswith("/object/sign/"):
            return Reply(json.dumps({"signedURL": path + "?token=synthetic"}).encode())
        key = path.removeprefix("/object/")
        writes.append((method, key))
        objects[key] = req.data
        if method == "PUT":
            updated = True
        return Reply(b"{}")

    monkeypatch.setattr(activation.urllib.request, "urlopen", request)
    if failure and failure != "delayed-read":
        with pytest.raises(ValueError):
            activation.activate(channel, target, tmp_path / "synthetic.env")
        assert writes == []
        assert objects[old_path] == old
        return
    result = activation.activate(channel, target, tmp_path / "synthetic.env")
    assert objects[result["backup_object_path"]] == old
    assert objects[new_path] == new
    pointer = json.loads(objects[old_path])
    assert pointer["schema_version"] == 2
    assert pointer["snapshot_url"] == target["signed_url"]
    assert pointer["sha256"] == hashlib.sha256(new).hexdigest()
    assert writes[-1] == ("PUT", old_path)
    assert result["signed_url"] == channel["signed_url"]
    assert sleeps == ([1] if failure == "delayed-read" else [])
