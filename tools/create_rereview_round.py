"""Publish fresh category batches and export frozen originals to private SQLite files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

from psycopg.rows import dict_row

from tools.common import AdminError, database_url
from tools.native_runtime import connect_admin


def validate_round_code(round_code: str) -> str:
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,29}", round_code):
        raise AdminError("Round code must contain 1-30 uppercase letters, digits or hyphens.")
    return round_code


def publication_sql(round_code: str, *, replace_existing: bool = False) -> str:
    return (
        Path(__file__)
        .with_name("rereview_round.sql")
        .read_text()
        .replace("ROUND_CODE", validate_round_code(round_code))
        .replace("REPLACE_EXISTING", "true" if replace_existing else "false")
    )


def regroup_sql(round_code: str) -> str:
    return (
        Path(__file__)
        .with_name("regroup_rereview_round.sql")
        .read_text()
        .replace("ROUND_CODE", validate_round_code(round_code))
    )


def snapshot_query(round_code: str) -> str:
    validate_round_code(round_code)
    return f"""select item.id::text as item_id, item.source_provider, item.image_id,
        item.image_url, item.display_url, campaign.target_scientific_name,
        campaign.campaign_code, batch.batch_code, item.position,
        item.pipeline_metadata->'_veritaxa_rereview' as provenance
      from public.review_items item
      join public.review_batches batch on batch.id = item.batch_id
      join public.review_campaigns campaign on campaign.id = batch.campaign_id
      where campaign.campaign_code ~ '^REREVIEW-{round_code}-[0-9]+$'
      order by campaign.campaign_code, batch.position, item.position"""


def category_filename(category: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")[:70] or "category"
    digest = hashlib.sha256(category.encode()).hexdigest()[:10]
    return f"{slug}-{digest}.sqlite3"


def _open_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    path.chmod(0o600)
    connection.executescript("""
      create table images (
        item_id text primary key, category text not null,
        source_provider text not null, image_id text not null,
        image_url text not null, display_url text, target_scientific_name text,
        campaign_code text not null, batch_code text not null, position integer not null,
        original_item_id text not null, snapshot_at text not null,
        unique(category, source_provider, image_id)
      );
      create table reviews (
        review_id text primary key, item_id text not null references images(item_id),
        label text not null, scientific_name text, reviewed_at text not null,
        original_review_json text not null
      );
    """)
    connection.execute("pragma foreign_keys = on")
    return connection


def _insert(connection: sqlite3.Connection, record: dict[str, object]) -> None:
    provenance = record["provenance"]
    if not isinstance(provenance, dict):
        raise AdminError("Missing re-review snapshot provenance.")
    connection.execute(
        "insert into images values (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["item_id"],
            provenance["category"],
            record["source_provider"],
            record["image_id"],
            record["image_url"],
            record["display_url"],
            record["target_scientific_name"],
            record["campaign_code"],
            record["batch_code"],
            record["position"],
            provenance["original_item_id"],
            provenance["snapshot_at"],
        ),
    )
    for review in provenance["source_reviews"]:
        connection.execute(
            "insert into reviews values (?,?,?,?,?,?)",
            (
                review["id"],
                record["item_id"],
                review["label"],
                review.get("scientificName"),
                review["updated_at"],
                json.dumps(review, ensure_ascii=False, sort_keys=True),
            ),
        )


def export_snapshots(records: Iterable[dict[str, object]], output: Path) -> dict[str, object]:
    """Publish the entire directory atomically; never overwrite an existing export."""
    if output.exists():
        raise AdminError("Export directory already exists; choose a fresh private destination.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".rereview-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir(mode=0o700)
        connections: dict[str, sqlite3.Connection] = {}
        manifest: dict[str, object] = {"categories": [], "images": 0, "reviews": 0}
        master = _open_database(stage / "all-reviews.sqlite3")
        try:
            for record in records:
                provenance = record["provenance"]
                if not isinstance(provenance, dict):
                    raise AdminError("Missing re-review snapshot provenance.")
                round_code = provenance["round_code"]
                if manifest.setdefault("round_code", round_code) != round_code:
                    raise AdminError("Cannot combine snapshots from different re-review rounds.")
                manifest.setdefault("snapshot_at", provenance["snapshot_at"])
                category = provenance["category"]
                if category not in connections:
                    connections[category] = _open_database(stage / category_filename(category))
                _insert(master, record)
                _insert(connections[category], record)
            if not connections:
                raise AdminError("No published re-review snapshots found.")
            for category, connection in sorted(connections.items()):
                images = connection.execute("select count(*) from images").fetchone()[0]
                reviews = connection.execute("select count(*) from reviews").fetchone()[0]
                manifest["categories"].append(
                    {
                        "category": category,
                        "file": category_filename(category),
                        "images": images,
                        "reviews": reviews,
                        "batch_codes": [
                            row[0]
                            for row in connection.execute(
                                "select distinct batch_code from images order by batch_code"
                            )
                        ],
                    }
                )
                manifest["images"] += images
                manifest["reviews"] += reviews
            manifest["unique_images"] = master.execute(
                "select count(*) from (select distinct source_provider,image_id from images)"
            ).fetchone()[0]
            for connection in [master, *connections.values()]:
                if connection.execute("pragma integrity_check").fetchone()[0] != "ok":
                    raise AdminError("SQLite integrity check failed.")
                if connection.execute("pragma foreign_key_check").fetchall():
                    raise AdminError("SQLite review references failed validation.")
                connection.commit()
        finally:
            master.close()
            for connection in connections.values():
                connection.close()
        manifest_path = stage / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        manifest_path.chmod(0o600)
        os.rename(stage, output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-code", required=True)
    parser.add_argument("--output", type=Path, required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--publish", action="store_true", help="Create fresh open review folders.")
    action.add_argument(
        "--regroup", action="store_true", help="Combine an existing round's batches by option."
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Archive older re-review rounds on publication.",
    )
    args = parser.parse_args()
    validate_round_code(args.round_code)
    if args.replace_existing and not args.publish:
        parser.error("--replace-existing requires --publish")
    if args.output.exists():
        raise AdminError("Export directory already exists.")
    with connect_admin(database_url()) as connection:
        if args.publish:
            connection.execute(
                publication_sql(args.round_code, replace_existing=args.replace_existing)
            )
            connection.commit()
        elif args.regroup:
            connection.execute(regroup_sql(args.round_code))
            connection.commit()
        connection.read_only = True
        with connection.cursor(row_factory=dict_row) as cursor:
            records = cursor.stream(snapshot_query(args.round_code), size=1)
            manifest = export_snapshots(records, args.output)
    print(json.dumps({key: value for key, value in manifest.items() if key != "categories"}))


if __name__ == "__main__":
    try:
        main()
    except AdminError as error:
        raise SystemExit(str(error)) from None
