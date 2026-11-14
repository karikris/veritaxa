"""Publish three disjoint review queues using each image's latest saved human answer."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.common import database_url
from tools.create_rereview_round import validate_round_code
from tools.native_runtime import connect_admin


def publication_sql() -> str:
    return Path(__file__).with_name("latest_review_groups.sql").read_text()


def review_window(day: date, timezone: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    return (
        datetime.combine(day, time.min, zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-code", required=True, type=validate_round_code)
    parser.add_argument("--target-name", required=True)
    parser.add_argument("--source-campaign", action="append", required=True)
    parser.add_argument("--reviewed-on", type=date.fromisoformat, required=True)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--reopen-source-batches", action="store_true")
    parser.add_argument("--include-other-model-campaign", action="append", default=[])
    parser.add_argument("--append-existing", action="store_true")
    parser.add_argument(
        "--publish", action="store_true", help="Commit; otherwise validate and roll back"
    )
    args = parser.parse_args()
    after, before = review_window(args.reviewed_on, args.timezone)
    with connect_admin(database_url()) as connection:
        connection.execute("select set_config('veritaxa.round_code', %s, true)", (args.round_code,))
        connection.execute(
            "select set_config('veritaxa.target_name', %s, true)", (args.target_name,)
        )
        for name, value in {
            "source_campaigns": json.dumps(args.source_campaign),
            "reviewed_after": after.isoformat(),
            "reviewed_before": before.isoformat(),
            "reopen_source_batches": str(args.reopen_source_batches).lower(),
            "other_model_campaigns": json.dumps(args.include_other_model_campaign),
            "append_existing": str(args.append_existing).lower(),
        }.items():
            connection.execute("select set_config(%s, %s, true)", (f"veritaxa.{name}", value))
        connection.execute(publication_sql())
        counts = connection.execute(
            "select category,count(*) from latest_group_additions "
            "group by category order by category"
        ).fetchall()
        if not args.publish:
            connection.rollback()
    print(json.dumps({"published": args.publish, "groups": dict(counts)}))


if __name__ == "__main__":
    main()
