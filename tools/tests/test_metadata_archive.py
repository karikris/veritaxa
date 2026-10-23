from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.common import AdminError
from tools.metadata_archive import (
    ARCHIVE_KEY,
    PROVENANCE_KEY,
    MetadataResolver,
    archive_large_candidates,
    archive_records,
    archive_reference,
    compact_metadata,
    load_archive_environment,
)


class MemoryStore:
    bucket = "synthetic-private"
    prefix = "synthetic/veritaxa/metadata-archives/"

    def __init__(self):
        self.objects = {}
        self.gets = []

    def check_private(self):
        pass

    def put(self, key, data):
        self.objects[key] = data

    def get(self, key):
        self.gets.append(key)
        return self.objects[key]


def record(identifier="synthetic-1", payload=None):
    text = json.dumps(payload or {"nested": [None, True, "🦋"], "score": 0.125})
    return {
        "record_id": identifier,
        "metadata_json": text,
        "metadata_md5": hashlib.md5(text.encode()).hexdigest(),
    }


def test_verified_round_trip_preserves_every_field_and_caches_shards(tmp_path: Path):
    store = MemoryStore()
    rows = [record(), record("synthetic-2", {"different": {"values": [1, 2]}})]
    archive = archive_records(iter(rows), store, tmp_path / "private")
    store.gets.clear()
    with MetadataResolver(store) as resolver:
        for row in rows:
            reference = archive_reference(archive, row["record_id"])
            actual = resolver.resolve({ARCHIVE_KEY: reference})
            assert actual == json.loads(row["metadata_json"])
        assert len(store.gets) == 2  # one manifest, one shard
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (tmp_path / "private").iterdir())


def test_missing_or_corrupt_objects_stop_export(tmp_path: Path):
    store = MemoryStore()
    archive = archive_records([record()], store, tmp_path / "private")
    reference = archive_reference(archive, "synthetic-1")
    key = archive["manifest"]["shards"][0]["key"]
    original = store.objects[key]
    store.objects[key] = b"corrupt"
    with MetadataResolver(store) as resolver, pytest.raises(AdminError, match="checksum"):
        resolver.resolve({ARCHIVE_KEY: reference})
    store.objects[key] = original
    del store.objects[key]
    with MetadataResolver(store) as resolver, pytest.raises(AdminError, match="Cannot restore"):
        resolver.resolve({ARCHIVE_KEY: reference})


def test_modified_manifest_is_rejected(tmp_path: Path):
    store = MemoryStore()
    archive = archive_records([record()], store, tmp_path / "private")
    reference = archive_reference(archive, "synthetic-1")
    key = archive["uri"].split(store.bucket + "/", 1)[1]
    store.objects[key] += b"changed"
    with MetadataResolver(store) as resolver, pytest.raises(AdminError, match="manifest checksum"):
        resolver.resolve({ARCHIVE_KEY: reference})


def test_failed_upload_never_returns_cleanup_references(tmp_path: Path):
    store = MemoryStore()
    store.get = lambda _key: b"bad download"
    with pytest.raises(AdminError, match="download verification"):
        archive_records([record()], store, tmp_path / "private")
    assert not any(key.endswith("manifest.json") for key in store.objects)


def test_cloned_reference_preserves_new_round_provenance(tmp_path: Path):
    store = MemoryStore()
    original = {"model": {"values": [1, 2]}, PROVENANCE_KEY: {"round_code": "SYNTH-OLD"}}
    archive = archive_records([record(payload=original)], store, tmp_path / "private")
    compact = compact_metadata(original, archive_reference(archive, "synthetic-1"))
    compact[PROVENANCE_KEY] = {"round_code": "SYNTH-NEW"}
    assert "model" not in compact
    with MetadataResolver(store) as resolver:
        restored = resolver.resolve(compact)
    assert restored == {**original, PROVENANCE_KEY: {"round_code": "SYNTH-NEW"}}


def test_reference_cannot_fetch_another_bucket_or_prefix(tmp_path: Path):
    store = MemoryStore()
    archive = archive_records([record()], store, tmp_path / "private")
    reference = archive_reference(archive, "synthetic-1")
    reference["manifest"] = "s3://another-private-bucket/stolen.json"
    with MetadataResolver(store) as resolver, pytest.raises(AdminError, match="outside"):
        resolver.resolve({ARCHIVE_KEY: reference})


def test_duplicate_or_changed_records_are_rejected(tmp_path: Path):
    store = MemoryStore()
    with pytest.raises(AdminError, match="Duplicate"):
        archive_records([record(), record()], store, tmp_path / "duplicates")
    changed = record()
    changed["metadata_json"] = "{}"
    with pytest.raises(AdminError, match="checksum"):
        archive_records([changed], store, tmp_path / "changed")


def test_import_archives_bulky_metadata_before_publication(tmp_path: Path):
    from tools.candidate_spool import validate_candidates

    rows = [
        {
            "image_id": "synthetic-1",
            "source_provider": "synthetic",
            "image_url": "https://images.example.invalid/synthetic.jpg",
            "pipeline_metadata": {"payload": "synthetic" * 2000},
        }
    ]
    store = MemoryStore()
    with validate_candidates(rows, temporary_parent=tmp_path) as spool:
        archive_large_candidates(spool, store)
        candidate = next(spool.chunks()).candidates[0]
        assert ARCHIVE_KEY in candidate.pipeline_metadata
        with MetadataResolver(store) as resolver:
            assert resolver.resolve(candidate.pipeline_metadata) == rows[0]["pipeline_metadata"]


def test_restoration_keeps_exact_numeric_literals(tmp_path: Path):
    text = '{"exact": 12345678901234567890.12345678901234567890}'
    row = {
        "record_id": "synthetic-precise",
        "metadata_json": text,
        "metadata_md5": hashlib.md5(text.encode()).hexdigest(),
    }
    store = MemoryStore()
    archive = archive_records([row], store, tmp_path / "private")
    with MetadataResolver(store) as resolver:
        reference = archive_reference(archive, row["record_id"])
        assert resolver.restore_text({ARCHIVE_KEY: reference}) == text


def test_shared_secret_file_is_parsed_without_executing_shell(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BIOMINER_S3_BUCKET", raising=False)
    path = tmp_path / "secrets.env"
    marker = tmp_path / "must-not-exist"
    path.write_text(f"export BIOMINER_S3_BUCKET='synthetic-private'\ntouch {marker}\n")
    load_archive_environment(path)
    import os

    assert os.environ["BIOMINER_S3_BUCKET"] == "synthetic-private"
    assert not marker.exists()
