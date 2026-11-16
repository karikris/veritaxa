"""Read a private local snapshot or a server-only HTTPS snapshot reference."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import requests

from apps.review_map.core import Snapshot, SnapshotError, parse_snapshot

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def load_snapshot(reference: str, *, local: bool) -> Snapshot:
    try:
        if local:
            with Path(reference).open("rb") as handle:
                body = handle.read(MAX_SNAPSHOT_BYTES + 1)
        else:
            parsed = urlsplit(reference)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise SnapshotError("Snapshot configuration requires HTTPS.")
            with requests.get(
                reference, timeout=(5, 25), stream=True, allow_redirects=False
            ) as reply:
                if reply.status_code != 200:
                    raise SnapshotError(
                        "Map data is unavailable. Check the snapshot configuration."
                    )
                parts, length = [], 0
                for part in reply.iter_content(64 * 1024):
                    length += len(part)
                    if length > MAX_SNAPSHOT_BYTES:
                        raise SnapshotError("Map snapshot is too large.")
                    parts.append(part)
                body = b"".join(parts)
        if len(body) > MAX_SNAPSHOT_BYTES:
            raise SnapshotError("Map snapshot is too large.")
        return parse_snapshot(json.loads(body))
    except (OSError, requests.RequestException, ValueError, TypeError) as error:
        if isinstance(error, SnapshotError):
            raise
        raise SnapshotError("Map data is unavailable. Check the snapshot configuration.") from None
