"""Separate missing-location images while preserving saved answers and item identities."""

import argparse
import json
from pathlib import Path

from tools.common import database_url
from tools.create_rereview_round import validate_round_code
from tools.native_runtime import connect_admin


def partition_sql():
    return Path(__file__).with_suffix(".sql").read_text()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-code", required=True, type=validate_round_code)
    p.add_argument("--source-campaign", action="append", required=True)
    p.add_argument("--batch-size", type=int, default=1000)
    p.add_argument("--publish", action="store_true")
    a = p.parse_args()
    with connect_admin(database_url()) as connection:
        for key, value in {
            "geotag_run_code": a.run_code,
            "geotag_source_campaigns": json.dumps(a.source_campaign),
            "geotag_batch_size": str(a.batch_size),
        }.items():
            connection.execute("select set_config(%s,%s,true)", ("veritaxa." + key, value))
        connection.execute(partition_sql())
        counts = connection.execute(
            "select review_round,campaign_name,images,batch_count from no_geo_groups "
            "order by review_round,campaign_name"
        ).fetchall()
        if not a.publish:
            connection.rollback()
    print(json.dumps({"published": a.publish, "groups": counts}))


if __name__ == "__main__":
    main()
