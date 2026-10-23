"""Restore an archived metadata run by original item IDs, preserving exact JSON values."""

from __future__ import annotations

import argparse
from pathlib import Path

from psycopg.types.json import Jsonb

from tools.common import database_url
from tools.metadata_archive import MetadataResolver, load_archive_environment
from tools.native_runtime import connect_admin


def restore_metadata(dsn: str, manifest_uri: str) -> int:
    count = 0
    with connect_admin(dsn) as connection, MetadataResolver() as resolver:
        connection.execute("set local lock_timeout = '15s'")
        connection.execute("lock table public.review_items in share row exclusive mode")
        with connection.cursor(name="veritaxa_metadata_restore") as cursor:
            cursor.itersize = 100
            cursor.execute(
                """select id,pipeline_metadata from public.review_items
              where pipeline_metadata->'_veritaxa_archive'->>'manifest'=%s order by id""",
                (manifest_uri,),
            )
            for identifier, metadata in cursor:
                original = resolver.restore_text(metadata)
                # PostgreSQL parses the original numeric literals directly.
                updated = connection.execute(
                    """update public.review_items
                  set pipeline_metadata=%s::jsonb || (pipeline_metadata-'_veritaxa_archive')
                  where id=%s and pipeline_metadata=%s""",
                    (original, identifier, Jsonb(metadata)),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("Metadata changed during restoration")
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-uri", required=True)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.env_file:
        load_archive_environment(args.env_file)
    print(f"Restored metadata for {restore_metadata(database_url(), args.manifest_uri)} items.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Metadata restoration failed; transaction rolled back.") from None
