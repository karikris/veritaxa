"""Read a private snapshot, directly or through a versioned private deployment pointer."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from apps.review_map.core import Snapshot, SnapshotError, parse_snapshot

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def _https_reference(reference: str):
    parsed = urlsplit(reference)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SnapshotError("Snapshot configuration requires HTTPS.")
    return parsed


def _read(reference: str, *, local: bool, refresh: bool = False) -> bytes:
    if local:
        with Path(reference).open("rb") as handle:
            body = handle.read(MAX_SNAPSHOT_BYTES + 1)
    else:
        parsed = _https_reference(reference)
        if refresh and parsed.path.startswith("/storage/v1/object/sign/"):
            query = parse_qsl(parsed.query, keep_blank_values=True)
            query.append(("_map_cache", str(int(time.time() // 30))))
            reference = urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")
            )
        with requests.get(reference, timeout=(5, 25), stream=True, allow_redirects=False) as reply:
            if reply.status_code != 200:
                raise SnapshotError("Map data is unavailable. Check the snapshot configuration.")
            parts, length = [], 0
            for part in reply.iter_content(64 * 1024):
                length += len(part)
                if length > MAX_SNAPSHOT_BYTES:
                    raise SnapshotError("Map snapshot is too large.")
                parts.append(part)
            body = b"".join(parts)
    if len(body) > MAX_SNAPSHOT_BYTES:
        raise SnapshotError("Map snapshot is too large.")
    return body


def load_snapshot(reference: str, *, local: bool) -> Snapshot:
    try:
        payload = json.loads(_read(reference, local=local, refresh=not local))
        if isinstance(payload, dict) and payload.get("schema_version") == 2:
            child = payload.get("snapshot_url")
            digest = payload.get("sha256")
            if (
                not isinstance(child, str)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise SnapshotError("Invalid map deployment pointer.")
            target = _https_reference(child)
            if not local:
                parent = _https_reference(reference)
                if (target.hostname, target.port) != (parent.hostname, parent.port):
                    raise SnapshotError("Map deployment pointer must use the same host.")
            body = _read(child, local=False)
            if hashlib.sha256(body).hexdigest() != digest:
                raise SnapshotError("Map snapshot checksum does not match its deployment pointer.")
            result = parse_snapshot(json.loads(body))
            if result.revision != payload.get("revision") or len(result.photos) != payload.get(
                "image_count"
            ):
                raise SnapshotError("Map snapshot does not match its deployment pointer.")
            return result
        return parse_snapshot(payload)
    except (OSError, requests.RequestException, ValueError, TypeError) as error:
        if isinstance(error, SnapshotError):
            raise
        raise SnapshotError("Map data is unavailable. Check the snapshot configuration.") from None
