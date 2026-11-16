"""Activate a verified private map snapshot without changing the Cloud secret."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import uuid4

from tools.attach_location_clues import RestAdmin


def _download(url: str) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_activation_check", uuid4().hex))
    address = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )
    try:
        with urllib.request.urlopen(address, timeout=45) as response:
            result = response.read(16 * 1024 * 1024 + 1)
    except urllib.error.URLError:
        raise RuntimeError("The private map object could not be downloaded.") from None
    if len(result) > 16 * 1024 * 1024:
        raise ValueError("Map object is too large.")
    return result


def activate(channel: dict, target: dict, env_file: Path) -> dict:
    cfg = RestAdmin(env_file)
    bucket = channel["bucket"]
    if (
        bucket != target["bucket"]
        or not channel.get("verified_private")
        or not target.get("verified_private")
    ):
        raise ValueError("Activation requires verified objects in the same private bucket.")
    origin = cfg.origin + "/storage/v1"
    for receipt in (channel, target):
        path = receipt["object_path"]
        if (
            not path.startswith(bucket + "/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or not receipt["signed_url"].startswith(origin + "/object/sign/" + path + "?")
        ):
            raise ValueError("Unexpected map object reference.")
    if channel["object_path"] == target["object_path"]:
        raise ValueError("The target must be a separate immutable snapshot.")
    headers = {
        "apikey": cfg.key,
        "Authorization": "Bearer " + cfg.key,
        "Content-Type": "application/json",
        "Cache-Control": "max-age=0",
    }

    def request(method: str, path: str, payload=None, *, raw=False):
        body = payload if raw else json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(origin + path, method=method, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                result = response.read()
                return json.loads(result) if result else None
        except urllib.error.HTTPError as error:
            try:
                info = json.load(error)
            except ValueError:
                info = {}
            if method == "POST" and path.startswith("/object/" + bucket + "/archive/"):
                if error.code == 409 or info.get("error") in {"Duplicate", "AlreadyExists"}:
                    return None
            raise RuntimeError(f"Private map activation failed (HTTP {error.code}).") from None

    if request("GET", "/bucket/" + bucket).get("public") is not False:
        raise ValueError("The map bucket must remain private.")
    old = _download(channel["signed_url"])
    expected = channel.get("anchor_sha256", channel["sha256"])
    if hashlib.sha256(old).hexdigest() != expected:
        raise ValueError("The active map changed; inspect it before replacing the pointer.")
    new = _download(target["signed_url"])
    if hashlib.sha256(new).hexdigest() != target["sha256"]:
        raise ValueError("Target map checksum does not match its verified receipt.")
    snapshot = json.loads(new)
    if (
        snapshot.get("schema_version") != 1
        or snapshot.get("image_count") != target["images"]
        or len(snapshot.get("images", [])) != target["images"]
        or not isinstance(snapshot.get("revision"), str)
    ):
        raise ValueError("Target is not a complete map snapshot.")
    backup = bucket + "/archive/" + hashlib.sha256(old).hexdigest() + ".json"
    request("POST", "/object/" + backup, old, raw=True)
    signed = request("POST", "/object/sign/" + backup, {"expiresIn": 60})
    path = signed.get("signedURL") or signed.get("signedUrl")
    if not isinstance(path, str) or not path.startswith("/object/sign/" + backup + "?"):
        raise RuntimeError("Unexpected private backup reference.")
    if hashlib.sha256(_download(origin + path)).hexdigest() != expected:
        raise RuntimeError("The previous map could not be backed up safely.")
    pointer = {
        "schema_version": 2,
        "snapshot_url": target["signed_url"],
        "sha256": target["sha256"],
        "image_count": target["images"],
        "revision": snapshot["revision"],
    }
    body = json.dumps(pointer, separators=(",", ":")).encode() + b"\n"
    if hashlib.sha256(_download(channel["signed_url"])).hexdigest() != expected:
        raise ValueError("The active map changed during preparation; no pointer was replaced.")
    request("PUT", "/object/" + channel["object_path"], body, raw=True)
    digest = hashlib.sha256(body).hexdigest()
    if hashlib.sha256(_download(channel["signed_url"])).hexdigest() != digest:
        raise RuntimeError("The active private pointer could not be verified.")
    return {
        **channel,
        "anchor_sha256": digest,
        "active_snapshot_sha256": target["sha256"],
        "active_snapshot_revision": snapshot["revision"],
        "images": target["images"],
        "backup_object_path": backup,
        "verified_private": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-receipt", type=Path, required=True)
    parser.add_argument("--snapshot-receipt", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    if args.private_output.exists():
        parser.error("Output already exists; choose a new receipt path.")
    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    result = activate(
        json.loads(args.channel_receipt.read_text()),
        json.loads(args.snapshot_receipt.read_text()),
        args.env_file,
    )
    with args.private_output.open("x") as handle:
        args.private_output.chmod(0o600)
        json.dump(result, handle, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({"activated": True, "images": result["images"], "private": True}))


if __name__ == "__main__":
    main()
