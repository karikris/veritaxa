"""Publish three disjoint review queues using each image's latest saved human answer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.common import database_url
from tools.create_rereview_round import validate_round_code
from tools.native_runtime import connect_admin


def publication_sql() -> str:
    return Path(__file__).with_name("latest_review_groups.sql").read_text()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-code", required=True, type=validate_round_code)
    parser.add_argument("--target-name", required=True)
    parser.add_argument(
        "--publish", action="store_true", help="Commit; otherwise validate and roll back"
    )
    args = parser.parse_args()
    with connect_admin(database_url()) as connection:
        connection.execute("select set_config('veritaxa.round_code', %s, true)", (args.round_code,))
        connection.execute(
            "select set_config('veritaxa.target_name', %s, true)", (args.target_name,)
        )
        connection.execute(publication_sql())
        counts = connection.execute(
            "select category,count(*) from latest_group_members group by category order by category"
        ).fetchall()
        if not args.publish:
            connection.rollback()
    print(json.dumps({"published": args.publish, "groups": dict(counts)}))


if __name__ == "__main__":
    main()
