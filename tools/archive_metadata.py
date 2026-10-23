"""Archive pipeline metadata, verify recovery, and reclaim physical database space."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from tools.common import AdminError, database_url
from tools.metadata_archive import (
    S3Store,
    archive_records,
    archive_reference,
    load_archive_environment,
)
from tools.native_runtime import connect_admin

AUDIT_SQL = """
select jsonb_build_object(
 'items', (select count(*) from public.review_items),
 'item_fields', (select md5(string_agg(md5(jsonb_build_array(
   id,batch_id,position,image_id,source_provider,source_record_id,display_url,
   image_url,source_page_url,flickr_search_term,source_labels,created_at)::text),'' order by id))
   from public.review_items),
 'reviews', (select count(*) from public.image_reviews),
 'review_fields', (select md5(string_agg(to_jsonb(r)::text,'' order by id))
   from public.image_reviews r),
 'batches', (select md5(string_agg(to_jsonb(b)::text,'' order by id))
   from public.review_batches b),
 'campaigns', (select md5(string_agg(to_jsonb(c)::text,'' order by id))
   from public.review_campaigns c))
"""
# Qualify the UUID column: bare `id` binds the text projection and sorts expanded JSON.
SNAPSHOT_SQL = """select id::text, pipeline_metadata::text, md5(pipeline_metadata::text),
 xmin::text, (pipeline_metadata->'_veritaxa_rereview')::text
 from public.review_items where pipeline_metadata is not null
 and not pipeline_metadata ? '_veritaxa_archive' order by public.review_items.id"""
CLEANUP_SQL = """update public.review_items item set pipeline_metadata =
 jsonb_build_object('_veritaxa_archive', staged.reference) ||
 case when staged.provenance is not null then
 jsonb_build_object('_veritaxa_rereview', staged.provenance)
 else '{}'::jsonb end
 from veritaxa_metadata_cleanup staged where item.id=staged.id
 and item.xmin::text=staged.row_version"""


def reclaim(connection) -> int:
    connection.autocommit = True
    connection.execute("set session characteristics as transaction read write")
    connection.execute("set lock_timeout = '15s'")
    connection.execute("set statement_timeout = 0")
    connection.execute("vacuum (full, analyze) public.review_items")
    return connection.execute("select pg_database_size(current_database())").fetchone()[0]


def archive_database(dsn: str, store, directory: Path, *, compact: bool = True) -> dict:
    report = {}
    # Archive under a read-only snapshot without holding up reviewers.
    with connect_admin(dsn) as connection:
        connection.read_only = True
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.execute("set local statement_timeout = 0")
        report["before_bytes"] = connection.execute(
            "select pg_database_size(current_database())"
        ).fetchone()[0]
        if directory.exists():
            raise AdminError("Archive output directory already exists; use a fresh destination.")
        directory.parent.mkdir(parents=True, exist_ok=True)
        staging_path = directory.parent / (directory.name + "-versions.sqlite")
        if staging_path.exists():
            raise AdminError("Archive staging file already exists; use a fresh destination.")
        staging = sqlite3.connect(staging_path)
        staging_path.chmod(0o600)
        staging.execute(
            "create table versions (id text primary key, version text, provenance text)"
        )

        def records():
            with connection.cursor(name="veritaxa_metadata_snapshot") as cursor:
                cursor.itersize = 128
                cursor.execute(SNAPSHOT_SQL)
                for identifier, payload, checksum, version, provenance in cursor:
                    staging.execute(
                        "insert into versions values (?,?,?)", (identifier, version, provenance)
                    )
                    yield {
                        "record_id": identifier,
                        "metadata_json": payload,
                        "metadata_md5": checksum,
                    }

        try:
            archive = archive_records(records(), store, directory)
            staging.commit()
        finally:
            staging.close()
        count = len(archive["manifest"]["records"])
        if count == 0:
            raise AdminError("No unarchived metadata remains; use --compact-only if required.")
    with connect_admin(dsn) as connection, sqlite3.connect(staging_path) as staging:
        connection.read_only = False
        connection.execute("set local lock_timeout = '15s'")
        connection.execute("set local statement_timeout = 0")
        connection.execute("""lock table public.review_campaigns, public.review_batches,
          public.review_items, public.image_reviews in share row exclusive mode""")
        before = connection.execute(AUDIT_SQL).fetchone()[0]
        connection.execute("""create temporary table veritaxa_metadata_cleanup (
          id uuid primary key, row_version text not null, reference jsonb not null, provenance jsonb
        ) on commit drop""")
        with (
            connection.cursor() as cursor,
            cursor.copy("copy veritaxa_metadata_cleanup from stdin") as copy,
        ):
            for record_id, version, provenance in staging.execute("select * from versions"):
                copy.write_row(
                    (
                        record_id,
                        version,
                        Jsonb(archive_reference(archive, record_id)),
                        Jsonb(provenance, dumps=lambda value: value)
                        if provenance is not None
                        else None,
                    )
                )
        updated = connection.execute(CLEANUP_SQL).rowcount
        if updated != count:
            raise AdminError("Metadata changed since archival; no cleanup was committed.")
        after = connection.execute(AUDIT_SQL).fetchone()[0]
        if before != after:
            raise AdminError("Review data changed during cleanup; transaction rolled back.")
        if connection.execute("""select count(*) from public.review_items item
          join veritaxa_metadata_cleanup staged on staged.id=item.id
          where item.pipeline_metadata->'_veritaxa_rereview' is distinct from staged.provenance
        """).fetchone()[0]:
            raise AdminError("Re-review provenance changed; transaction rolled back.")
        report.update(
            archive_uri=archive["uri"],
            manifest_sha256=archive["sha256"],
            archived_items=count,
            preserved=before,
            cleanup_committed=False,
        )
        path = directory / "maintenance-report.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
        path.chmod(0o600)
        connection.commit()
        report["cleanup_committed"] = True
        path.write_text(json.dumps(report, indent=2) + "\n")
        if compact:
            report["after_bytes"] = reclaim(connection)
            report["below_target"] = report["after_bytes"] < 250 * 1024 * 1024
            path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact-only", action="store_true")
    args = parser.parse_args()
    if args.env_file:
        load_archive_environment(args.env_file)
    if args.compact_only:
        with connect_admin(database_url()) as connection:
            print(json.dumps({"after_bytes": reclaim(connection)}))
    else:
        if args.output is None:
            parser.error("--output is required for archival")
        report = archive_database(database_url(), S3Store(), args.output)
        print(json.dumps({k: v for k, v in report.items() if k != "preserved"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if isinstance(error, AdminError):
            raise SystemExit(str(error)) from None
        state = getattr(error, "sqlstate", None)
        raise SystemExit(
            f"Metadata maintenance failed ({type(error).__name__}, {state}); "
            "inspect private recovery files."
        ) from None
