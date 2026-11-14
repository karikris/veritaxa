"""Attach private location evidence with conditional REST updates and read-back checks."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shlex
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tools.common import AdminError, supabase_project_url
from tools.location_clue_groups import METADATA_KEY


class RestAdmin:
    def __init__(self, env_file: Path):
        accepted = {
            "SUPABASE_URL",
            "SUPABASE_JWKS_URL",
            "SUPABASE_SECRET_KEY",
            "VERITAXA_SUPABASE_URL",
            "SUPABASE_PROJECT_URL",
        }
        for raw in env_file.read_text().splitlines():
            line = raw.strip().removeprefix("export ")
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() in accepted:
                parts = shlex.split(value, comments=True)
                if len(parts) == 1:
                    os.environ.setdefault(name.strip(), parts[0])
        self.origin = supabase_project_url()
        self.key = os.environ["SUPABASE_SECRET_KEY"]

    def request(self, method: str, table: str, params: dict, body=None):
        url = self.origin + "/rest/v1/" + table + "?" + urllib.parse.urlencode(params)
        data = (
            None
            if body is None
            else json.dumps(
                body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
        )
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "apikey": self.key,
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
        )
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code in {429, 500, 502, 503, 504} and attempt < 4:
                    time.sleep(min(2**attempt, 16))
                    continue
                raise AdminError(f"REST {method} failed with HTTP {error.code}.") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt < 4:
                    time.sleep(min(2**attempt, 16))
                    continue
                raise AdminError("REST request timed out; resume using the same plan.") from None


def merge_metadata(row: dict, plan: dict) -> dict:
    if (
        row["id"] != plan["item_id"]
        or row["source_provider"] != plan["source_provider"]
        or row["source_record_id"] != plan["source_record_id"]
    ):
        raise AdminError("Live item identity does not match the frozen evidence plan.")
    metadata = row.get("pipeline_metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise AdminError("Pipeline metadata must be a JSON object.")
    existing = (metadata or {}).get(METADATA_KEY)
    if (
        existing is not None
        and existing != plan["payload"]
        and (
            not isinstance(existing, dict)
            or existing.get("status") != "unverified_requires_human_location_review"
        )
    ):
        raise AdminError("Existing adjudicated or unfamiliar location evidence cannot be replaced.")
    return {**(metadata or {}), METADATA_KEY: plan["payload"]}


def attach_one(client, row: dict, plan: dict) -> str:
    for _attempt in range(3):
        merged = merge_metadata(row, plan)
        old = row.get("pipeline_metadata")
        if old == merged:
            return "already_attached"
        params = {
            "id": "eq." + row["id"],
            "batch_id": "eq." + row["batch_id"],
            "select": "id,pipeline_metadata",
        }
        params["pipeline_metadata"] = (
            "is.null"
            if old is None
            else "eq." + json.dumps(old, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        )
        result = client.request("PATCH", "review_items", params, {"pipeline_metadata": merged})
        if len(result) == 1:
            if result[0]["id"] != row["id"] or result[0]["pipeline_metadata"] != merged:
                raise AdminError("Metadata read-back differs from the planned merge.")
            return "attached"
        if result:
            raise AdminError("Conditional update affected unexpected rows.")
        fresh = client.request(
            "GET",
            "review_items",
            {
                "id": "eq." + row["id"],
                "select": "id,batch_id,source_provider,source_record_id,pipeline_metadata",
            },
        )
        if len(fresh) != 1 or fresh[0]["batch_id"] != row["batch_id"]:
            raise AdminError("Item moved or disappeared while attaching clues.")
        row = fresh[0]
    raise AdminError("Concurrent metadata edits prevented attachment; no overwrite performed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        raise AdminError("Workers must be between 1 and 12.")
    with gzip.open(args.plan, "rt", encoding="utf8") as file:
        plans = [json.loads(line) for line in file if line.strip()]
    if len({p["item_id"] for p in plans}) != len(plans):
        raise AdminError("Duplicate plan item IDs.")
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    client = RestAdmin(args.env_file)
    rows = {}
    for offset in range(0, len(plans), 100):
        ids = [p["item_id"] for p in plans[offset : offset + 100]]
        response = client.request(
            "GET",
            "review_items",
            {
                "select": "id,batch_id,source_provider,source_record_id,pipeline_metadata",
                "id": "in.(" + ",".join(ids) + ")",
                "limit": 100,
            },
        )
        rows.update((row["id"], row) for row in response)
    if len(rows) != len(plans):
        raise AdminError("Not every planned image exists in the live database.")
    for plan in plans:
        merge_metadata(rows[plan["item_id"]], plan)
    batches = client.request(
        "GET",
        "review_batches",
        {
            "select": "id,status,review_campaigns!inner(status)",
            "id": "in.(" + ",".join(sorted({r["batch_id"] for r in rows.values()})) + ")",
        },
    )
    if any(b["status"] != "open" or b["review_campaigns"]["status"] != "open" for b in batches):
        raise AdminError("A planned image's dataset is no longer live.")
    backup = args.output / "metadata-before.json.gz"
    if not backup.exists():
        with gzip.open(backup, "wt", encoding="utf8") as file:
            json.dump(list(rows.values()), file, ensure_ascii=False)
        backup.chmod(0o600)
    max_query = max(
        len(
            urllib.parse.urlencode(
                {
                    "pipeline_metadata": "eq."
                    + json.dumps(r["pipeline_metadata"], ensure_ascii=False, separators=(",", ":"))
                }
            )
        )
        for r in rows.values()
    )
    print(
        json.dumps(
            {
                "validated_images": len(plans),
                "max_conditional_filter_bytes": max_query,
                "publish": args.publish,
            }
        ),
        flush=True,
    )
    if not args.publish:
        return
    counts = {"attached": 0, "already_attached": 0, "failed": 0}
    lock = threading.Lock()
    with (args.output / "attachment-results.jsonl").open("a", encoding="utf8") as log:

        def work(plan):
            try:
                state = attach_one(client, rows[plan["item_id"]], plan)
                result = {"item_id": plan["item_id"], "state": state}
            except Exception as error:
                state = "failed"
                result = {
                    "item_id": plan["item_id"],
                    "state": state,
                    "error": str(error) if isinstance(error, AdminError) else type(error).__name__,
                }
            with lock:
                counts[state] += 1
                log.write(json.dumps(result) + "\n")
                log.flush()
                if sum(counts.values()) % 100 == 0:
                    print(json.dumps(counts), flush=True)

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for future in as_completed(executor.submit(work, plan) for plan in plans):
                future.result()
    (args.output / "attachment-result.json").write_text(json.dumps(counts, indent=2))
    print(json.dumps(counts), flush=True)
    if counts["failed"]:
        raise AdminError("Some images need retry; successful attachments and backups are retained.")


if __name__ == "__main__":
    try:
        main()
    except AdminError as error:
        raise SystemExit(str(error)) from None
