"""Publish an immutable map snapshot to private Storage and save a server-only URL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.attach_location_clues import RestAdmin


def publish(snapshot_path: Path, env_file: Path, bucket: str, expires: int) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", bucket):
        raise ValueError("Invalid private bucket name.")
    if not 60 <= expires <= 31_536_000:
        raise ValueError("Signed URL lifetime must be between one minute and one year.")
    body = snapshot_path.read_bytes()
    snapshot = json.loads(body)
    images = snapshot.get("images")
    if (
        snapshot.get("schema_version") != 1
        or not isinstance(images, list)
        or not images
        or snapshot.get("image_count") != len(images)
    ):
        raise ValueError("Invalid map snapshot.")
    cfg = RestAdmin(env_file)
    origin = cfg.origin + "/storage/v1"
    headers = {"apikey": cfg.key, "Authorization": "Bearer " + cfg.key}

    def request(method: str, path: str, payload=None, *, raw=False):
        encoded = payload if raw else json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            origin + path,
            method=method,
            data=encoded,
            headers={**headers, "Content-Type": "application/json", "x-upsert": "false"},
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                result = response.read()
                return json.loads(result) if result else None
        except urllib.error.HTTPError as error:
            # Do not print request headers, bearer tokens or response payloads.
            try:
                payload = json.load(error)
            except ValueError:
                payload = {}
            if method == "GET" and path.startswith("/bucket/"):
                if str(payload.get("statusCode")) == "404" or error.code == 404:
                    return None
            if (
                method == "POST"
                and path.startswith("/object/")
                and not path.startswith("/object/sign/")
                and (
                    str(payload.get("statusCode")) == "409"
                    or payload.get("error") in {"Duplicate", "AlreadyExists"}
                )
            ):
                # Reuse the content-addressed object; the signed download below
                # must still pass the full checksum verification.
                return {"exists": True}
            raise RuntimeError(f"Private Storage request failed (HTTP {error.code}).") from None

    config = request("GET", "/bucket/" + bucket)
    if config is None:
        request("POST", "/bucket", {"id": bucket, "name": bucket, "public": False})
        config = request("GET", "/bucket/" + bucket)
    if config.get("public") is not False:
        raise ValueError("The selected bucket is public; choose a new private bucket.")
    digest = hashlib.sha256(body).hexdigest()
    object_path = bucket + "/snapshots/" + digest + ".json"
    request("POST", "/object/" + object_path, body, raw=True)
    signed = request("POST", "/object/sign/" + object_path, {"expiresIn": expires})
    signed_path = signed.get("signedURL") or signed.get("signedUrl")
    if not isinstance(signed_path, str) or not signed_path.startswith(
        "/object/sign/" + bucket + "/"
    ):
        raise RuntimeError("Storage did not return the expected private download URL.")
    signed_url = origin + signed_path
    try:
        with urllib.request.urlopen(signed_url, timeout=45) as response:
            downloaded = response.read(len(body) + 1)
    except urllib.error.URLError:
        raise RuntimeError("The private map snapshot could not be verified.") from None
    if hashlib.sha256(downloaded).hexdigest() != digest:
        raise RuntimeError("Published map snapshot checksum does not match.")
    return {
        "schema_version": 1,
        "bucket": bucket,
        "object_path": object_path,
        "sha256": digest,
        "images": snapshot["image_count"],
        "signed_url": signed_url,
        "expires_at": (datetime.now(UTC) + timedelta(seconds=expires)).isoformat(),
        "verified_private": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--bucket", default="review-map-snapshots")
    parser.add_argument("--expires-in", type=int, default=31_536_000)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    if args.private_output.exists():
        parser.error("Private output exists; choose a new path.")
    result = publish(args.snapshot, args.env_file, args.bucket, args.expires_in)
    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    with args.private_output.open("x") as handle:
        args.private_output.chmod(0o600)
        json.dump(result, handle, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({"images": result["images"], "private": True, "checksum_verified": True}))


if __name__ == "__main__":
    main()
