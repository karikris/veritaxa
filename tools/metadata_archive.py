"""Private, checksum-verified metadata archives on S3-compatible storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sqlite3
from collections.abc import Iterable
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4

import polars as pl

from tools.common import AdminError, load_admin_environment
from tools.native_runtime import require_runtime
from tools.tabular_output import write_records

ARCHIVE_KEY = "_veritaxa_archive"
PROVENANCE_KEY = "_veritaxa_rereview"
SCHEMA = pl.Schema({"record_id": pl.String, "metadata_json": pl.String, "metadata_md5": pl.String})
MAX_SHARD_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024 * 1024


def load_archive_environment(path: Path) -> None:
    """Read relevant literal assignments from a shared shell file without executing it."""
    accepted = {
        "VERITAXA_DATABASE_URL",
        "SUPABASE_DB_URL",
        "DATABASE_URL",
        "BIOMINER_WORKSTORE_DSN",
        "AWS_DEFAULT_REGION",
    }
    for line in path.read_text().splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not match:
            continue
        name, literal = match.groups()
        if name not in accepted and not name.startswith("BIOMINER_S3_"):
            continue
        parts = shlex.split(literal, comments=True)
        if len(parts) > 1 or "$" in literal or "`" in literal:
            raise AdminError("Archive environment requires literal credential assignments.")
        os.environ.setdefault(name, parts[0] if parts else "")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class S3Store:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        require_runtime()
        load_admin_environment()
        self.bucket = os.environ.get("BIOMINER_S3_BUCKET", "").strip()
        prefix = os.environ.get("BIOMINER_S3_PREFIX", "biominer").strip("/")
        self.prefix = f"{prefix}/veritaxa/metadata-archives/"
        endpoint = os.environ.get("BIOMINER_S3_ENDPOINT_URL", "").strip()
        if endpoint and "://" not in endpoint:
            endpoint = "https://" + endpoint
        parsed = urlsplit(endpoint)
        if endpoint and (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise AdminError("Archive endpoint must be a credential-free HTTPS origin.")
        if not self.bucket:
            raise AdminError("Configure the private metadata archive bucket.")
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        if parsed.hostname and parsed.hostname.endswith(".backblazeb2.com"):
            region = parsed.hostname.split(".")[1]
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            region_name=region,
            aws_access_key_id=os.environ.get("BIOMINER_S3_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("BIOMINER_S3_SECRET_ACCESS_KEY"),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def check_private(self) -> None:
        acl = self.client.get_bucket_acl(Bucket=self.bucket)
        for grant in acl.get("Grants", []):
            if grant.get("Grantee", {}).get("Type") == "Group":
                raise AdminError("Metadata archive bucket must be private.")

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ServerSideEncryption="AES256"
        )

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        with response["Body"] as body:
            return body.read()


def compact_metadata(metadata: dict, reference: dict) -> dict:
    result = {ARCHIVE_KEY: reference}
    if PROVENANCE_KEY in metadata:
        result[PROVENANCE_KEY] = metadata[PROVENANCE_KEY]
    return result


def archive_records(records: Iterable[dict[str, str]], store, directory: Path) -> dict:
    """Upload and read back every shard and manifest before returning any references."""
    store.check_private()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    archive_id = uuid4().hex
    base = store.prefix + archive_id + "/"
    manifest = {"version": 1, "archive_id": archive_id, "shards": [], "records": {}}
    pending = []
    pending_bytes = 0

    def flush() -> None:
        if not pending:
            return
        number = len(manifest["shards"])
        filename = f"metadata-{number:05d}.parquet"
        path = directory / filename
        write_records(pending, SCHEMA, path)
        data = path.read_bytes()
        key = base + filename
        store.put(key, data)
        downloaded = store.get(key)
        if sha256(downloaded) != sha256(data):
            raise AdminError("Uploaded metadata shard failed download verification.")
        # Verify decoded content too, including all identifiers and exact JSON text.
        if pl.read_parquet(downloaded).to_dicts() != pending:
            raise AdminError("Uploaded metadata records failed restoration verification.")
        manifest["shards"].append({"key": key, "sha256": sha256(data), "rows": len(pending)})
        for record in pending:
            manifest["records"][record["record_id"]] = {
                "shard": number,
                "metadata_md5": record["metadata_md5"],
            }
        pending.clear()

    for record in records:
        size = len(record["metadata_json"].encode())
        if size > MAX_METADATA_BYTES:
            raise AdminError("Metadata exceeds the 16 MiB archive record limit.")
        if record["record_id"] in manifest["records"] or any(
            row["record_id"] == record["record_id"] for row in pending
        ):
            raise AdminError("Duplicate metadata archive identifier.")
        if hashlib.md5(record["metadata_json"].encode()).hexdigest() != record["metadata_md5"]:
            raise AdminError("Metadata snapshot checksum mismatch.")
        if pending and (pending_bytes + size > MAX_SHARD_BYTES or len(pending) >= 1000):
            flush()
            pending_bytes = 0
        pending.append(record)
        pending_bytes += size
    flush()
    data = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = directory / "manifest.json"
    path.write_bytes(data)
    path.chmod(0o600)
    key = base + "manifest.json"
    store.put(key, data)
    if store.get(key) != data:
        raise AdminError("Uploaded archive manifest failed download verification.")
    return {"manifest": manifest, "uri": f"s3://{store.bucket}/{key}", "sha256": sha256(data)}


def archive_reference(archive: dict, record_id: str) -> dict:
    return {
        "manifest": archive["uri"],
        "manifest_sha256": archive["sha256"],
        "record_id": record_id,
        "metadata_md5": archive["manifest"]["records"][record_id]["metadata_md5"],
    }


class MetadataResolver:
    """Fetch each shard once; use a private disk cache instead of retaining the dataset."""

    def __init__(self, store=None) -> None:
        self.store = store
        self.temporary = TemporaryDirectory(prefix="veritaxa-metadata-")
        self.directory = Path(self.temporary.name)
        self.cache = sqlite3.connect(self.directory / "cache.sqlite")
        self.cache.execute(
            "create table records (manifest text, id text, payload text, primary key(manifest,id))"
        )
        self.manifests = {}
        self.loaded = set()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.cache.close()
        self.temporary.cleanup()

    def resolve(self, metadata):
        if not isinstance(metadata, dict) or ARCHIVE_KEY not in metadata:
            return metadata
        restored = json.loads(self.restore_text(metadata))
        # New rounds may override provenance while sharing archived source metadata.
        restored.update({k: v for k, v in metadata.items() if k != ARCHIVE_KEY})
        return restored

    def restore_text(self, metadata):
        """Return exact PostgreSQL JSON text, preserving arbitrary numeric precision."""
        try:
            reference = metadata[ARCHIVE_KEY]
            uri = reference["manifest"]
            if self.store is None:
                self.store = S3Store()
            parsed = urlsplit(uri)
            key = parsed.path.lstrip("/")
            if (
                parsed.scheme != "s3"
                or parsed.netloc != self.store.bucket
                or not key.startswith(self.store.prefix)
                or ".." in key.split("/")
            ):
                raise AdminError("Metadata archive reference is outside the configured archive.")
            digest = reference["manifest_sha256"]
            if not re.fullmatch("[0-9a-f]{64}", digest):
                raise AdminError("Invalid archive manifest checksum.")
            if digest not in self.manifests:
                data = self.store.get(key)
                if sha256(data) != digest:
                    raise AdminError("Metadata archive manifest checksum mismatch.")
                manifest = json.loads(data)
                if manifest["version"] != 1:
                    raise AdminError("Unsupported metadata archive version.")
                self.manifests[digest] = manifest
            manifest = self.manifests[digest]
            record_id = reference["record_id"]
            entry = manifest["records"][record_id]
            shard_number = entry["shard"]
            if (digest, shard_number) not in self.loaded:
                shard = manifest["shards"][shard_number]
                if not shard["key"].startswith(key.rsplit("/", 1)[0] + "/"):
                    raise AdminError("Metadata shard is outside its archive.")
                data = self.store.get(shard["key"])
                if sha256(data) != shard["sha256"]:
                    raise AdminError("Metadata archive shard checksum mismatch.")
                frame = pl.read_parquet(data)
                if frame.height != shard["rows"]:
                    raise AdminError("Metadata archive shard row count mismatch.")
                for row in frame.iter_rows(named=True):
                    payload = row["metadata_json"]
                    md5 = hashlib.md5(payload.encode()).hexdigest()
                    expected = manifest["records"][row["record_id"]]
                    if md5 != row["metadata_md5"] or md5 != expected["metadata_md5"]:
                        raise AdminError("Archived metadata record checksum mismatch.")
                    self.cache.execute(
                        "insert into records values (?,?,?)", (digest, row["record_id"], payload)
                    )
                self.loaded.add((digest, shard_number))
            row = self.cache.execute(
                "select payload from records where manifest=? and id=?", (digest, record_id)
            ).fetchone()
            if row is None or hashlib.md5(row[0].encode()).hexdigest() != reference["metadata_md5"]:
                raise AdminError("Archived metadata record is missing or changed.")
            return row[0]
        except AdminError:
            raise
        except Exception as error:
            raise AdminError("Cannot restore archived metadata; export stopped.") from error


def archive_large_candidates(spool, store=None, *, threshold: int = 8192) -> None:
    """Replace bulky validated payloads before database credentials are resolved."""

    def records():
        for ordinal, payload in spool.connection.execute(
            "select ordinal,payload from candidates order by ordinal"
        ):
            metadata = json.loads(payload).get("pipeline_metadata")
            if not metadata or ARCHIVE_KEY in metadata:
                continue
            text = json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if len(text.encode()) >= threshold:
                yield {
                    "record_id": str(ordinal),
                    "metadata_json": text,
                    "metadata_md5": hashlib.md5(text.encode()).hexdigest(),
                }

    pending = iter(records())
    first = next(pending, None)
    if first is None:
        return
    with TemporaryDirectory(prefix="veritaxa-import-archive-") as temporary:
        archive = archive_records(
            chain([first], pending), store or S3Store(), Path(temporary) / "archive"
        )
        spool.connection.execute("pragma query_only = false")
        try:
            for identifier in archive["manifest"]["records"]:
                ordinal = int(identifier)
                payload = json.loads(
                    spool.connection.execute(
                        "select payload from candidates where ordinal=?", (ordinal,)
                    ).fetchone()[0]
                )
                payload["pipeline_metadata"] = compact_metadata(
                    payload["pipeline_metadata"], archive_reference(archive, identifier)
                )
                spool.connection.execute(
                    "update candidates set payload=? where ordinal=?",
                    (json.dumps(payload).encode(), ordinal),
                )
            spool.connection.commit()
        finally:
            spool.connection.execute("pragma query_only = true")
