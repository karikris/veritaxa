"""Adapters for Flickr export fields and read-only cached getInfo locations."""

import json
import sqlite3
from pathlib import Path

from .common import dump
from .coordinates import valid_coordinates
from .html_text import visible


def units(row):
    owner = row.get("owner_id") or ""
    current_owner = json.loads(row.get("flickr_current_owner_json") or "{}")
    owner = current_owner.get("nsid") or owner
    emitted = set()
    for source, fields in [
        ("title", ["flickr_current_title", "raw_title"]),
        ("description", ["flickr_current_description", "raw_description"]),
    ]:
        for field in fields:
            text, links = visible(row.get(field))
            if text and (source, text) not in emitted:
                emitted.add((source, text))
                yield dict(
                    source=source,
                    field=field,
                    text=text,
                    links=links,
                    author_is_owner=True,
                    comment_id=None,
                    comment_author=None,
                    comment_created_at=None,
                )
    tags = json.loads(row.get("flickr_current_tags_json") or "{}").get("tag", [])
    tag_texts = [(t.get("raw") or t.get("_content") or "", t.get("author")) for t in tags]
    tag_texts += [(t, None) for t in str(row.get("raw_tags") or "").split()]
    emitted_tags = set()
    for raw, author in tag_texts:
        if raw in emitted_tags:
            continue
        emitted_tags.add(raw)
        if ":" in raw and "=" in raw and not raw.lower().startswith("geo"):
            continue
        text, links = visible(raw)
        if text:
            yield dict(
                source="tag",
                field="flickr_current_tags_json/raw_tags",
                text=text,
                links=links,
                author_is_owner=(author == owner) if author else None,
                comment_id=None,
                comment_author=author,
                comment_created_at=None,
            )
    for comment in json.loads(row.get("flickr_comments_json") or "[]"):
        text, links = visible(comment.get("_content"))
        if text:
            yield dict(
                source="comment",
                field="flickr_comments_json",
                text=text,
                links=links,
                author_is_owner=comment.get("author") == owner,
                comment_id=comment.get("id"),
                comment_author=comment.get("author"),
                comment_created_at=comment.get("datecreate"),
            )
    profile = current_owner.get("location")
    if profile:
        yield dict(
            source="owner_profile",
            field="flickr_current_owner_json.location",
            text=str(profile),
            links=[],
            author_is_owner=True,
            comment_id=None,
            comment_author=None,
            comment_created_at=None,
        )


def source_locations(cache_path, ids):
    connection = sqlite3.connect(f"file:{Path(cache_path).resolve()}?mode=ro", uri=True)
    result, snapshots = {}, []
    try:
        for pid, status, payload, retrieved in connection.execute(
            "SELECT photo_id,status,payload,retrieved_at FROM responses WHERE endpoint='info'"
        ):
            if pid not in ids:
                continue
            location = (
                json.loads(payload).get("photo", {}).get("location") if status == "ok" else None
            )
            snapshots.append(
                dict(
                    flickr_photo_id=pid,
                    status=status,
                    retrieved_at=retrieved,
                    provider_location_json=dump(location) if location else None,
                )
            )
            if location and (
                coordinates := valid_coordinates(
                    location.get("latitude"), location.get("longitude")
                )
            ):
                result[pid] = dict(
                    latitude=coordinates[0],
                    longitude=coordinates[1],
                    location=location,
                    retrieved_at=retrieved,
                )
    finally:
        connection.close()
    return result, snapshots
