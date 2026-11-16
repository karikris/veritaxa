from __future__ import annotations

import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from tools import publish_review_map


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_storage_publication_is_private_and_checks_the_download(tmp_path, monkeypatch):
    source = tmp_path / "snapshot.json"
    body = json.dumps(
        {"schema_version": 1, "image_count": 1, "images": [{"key": "synthetic"}]}
    ).encode()
    source.write_bytes(body)
    calls = []
    origin = "https://project.example.invalid"
    monkeypatch.setattr(
        publish_review_map,
        "RestAdmin",
        lambda _: SimpleNamespace(origin=origin, key="synthetic-admin-value"),
    )

    def request(req, timeout):
        assert timeout == 45
        if isinstance(req, str):
            assert req.startswith(origin + "/storage/v1/object/sign/private-map/")
            return Reply(body)
        calls.append((req.get_method(), req.full_url, req.data))
        if req.get_method() == "GET":
            return Reply(json.dumps({"public": False}).encode())
        if "/object/sign/" in req.full_url:
            path = req.full_url.removeprefix(origin + "/storage/v1")
            return Reply(
                json.dumps({"signedURL": path + "?token=synthetic-download-value"}).encode()
            )
        return Reply(b"{}")

    monkeypatch.setattr(publish_review_map.urllib.request, "urlopen", request)
    result = publish_review_map.publish(source, tmp_path / "synthetic.env", "private-map", 3600)
    assert result["verified_private"] is True
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    upload = next(call for call in calls if "/object/private-map/" in call[1])
    assert upload[2] == body


def test_public_bucket_is_rejected_before_upload(tmp_path, monkeypatch):
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps({"schema_version": 1, "image_count": 1, "images": [{}]}))
    monkeypatch.setattr(
        publish_review_map,
        "RestAdmin",
        lambda _: SimpleNamespace(origin="https://project.example.invalid", key="synthetic"),
    )
    monkeypatch.setattr(
        publish_review_map.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Reply(b'{"public":true}'),
    )
    with pytest.raises(ValueError, match="public"):
        publish_review_map.publish(source, tmp_path / "synthetic.env", "public-map", 3600)
