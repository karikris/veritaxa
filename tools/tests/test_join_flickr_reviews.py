import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import polars as pl

from tools.join_flickr_reviews import (
    build_rows,
    enrichment,
    load_reviews,
    open_cache,
    refresh,
    response_status,
    write_outputs,
)


class JoinTests(unittest.TestCase):
    def setUp(self):
        self.cache = open_cache(":memory:")
        self.source = pl.DataFrame(
            {
                "source": ["flickr", "flickr"],
                "flickr_photo_id": ["001", "002"],
                "latitude": [0.0, 0.0],
                "longitude": [0.0, 0.0],
                "accuracy": [0, 0],
                "all_query_terms": [["a", "b"], ["b"]],
            }
        )
        self.review = {
            "source_provider": "flickr",
            "metadata.flickr_photo_id": "001",
            "image_id": "sha256:test",
            "first_round_review_count": "2",
            "first_round_reviewer_count": "2",
            "first_round_has_conflicting_reviews": "true",
            "first_round_reviews_json": json.dumps(
                [
                    {
                        "review_id": "a",
                        "comment": "first",
                        "database_review_json": {"duplicate": True},
                    },
                    {"review_id": "b", "comment": "second"},
                ]
            ),
            "second_round_reviews_json": "[]",
        }

    def tearDown(self):
        self.cache.close()

    def test_join_preserves_population_multiple_reviews_and_query_associations(self):
        rows = build_rows(self.source, [self.review], self.cache)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["has_saved_review"])
        self.assertFalse(rows[1]["has_saved_review"])
        self.assertEqual(len(json.loads(rows[0]["first_round_reviews_json"])), 2)
        self.assertNotIn("database_review_json", rows[0]["first_round_reviews_json"])
        self.assertEqual(json.loads(rows[0]["all_query_terms"]), ["a", "b"])
        self.assertIsNone(rows[0]["latitude"])
        self.assertEqual(rows[0]["flickr_geo_status"], "pending")

    def test_fail_closed_on_unmatched_or_duplicate_keys(self):
        with self.assertRaises(ValueError):
            build_rows(self.source, [self.review, self.review], self.cache)
        with self.assertRaises(ValueError):
            build_rows(
                self.source, [{**self.review, "metadata.flickr_photo_id": "999"}], self.cache
            )
        with self.assertRaises(ValueError):
            build_rows(pl.concat([self.source, self.source]), [], self.cache)

    def put(self, endpoint, payload):
        self.cache.execute(
            "INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?)",
            ("001", endpoint, "ok", json.dumps(payload), "2026-11-11"),
        )
        self.cache.commit()

    def test_public_geo_on_equator_and_comments_remain_single_row(self):
        self.put(
            "geo", {"photo": {"location": {"latitude": "0", "longitude": "20", "accuracy": "16"}}}
        )
        self.put(
            "comments",
            {
                "comments": {
                    "comment": [{"id": "a", "_content": "one"}, {"id": "b", "_content": "two"}]
                }
            },
        )
        rows = build_rows(self.source, [self.review], self.cache)
        self.assertEqual(rows[0]["latitude"], 0)
        self.assertEqual(rows[0]["longitude"], 20)
        self.assertEqual(rows[0]["flickr_comments_retrieved_count"], 2)
        self.assertEqual(len(rows), 2)

    def test_empty_comments_and_bad_geo(self):
        self.put("comments", {"comments": {}})
        self.put("geo", {"photo": {"location": {"latitude": "91", "longitude": "0"}}})
        result = enrichment(self.cache, "001")
        self.assertEqual(result["flickr_comments_json"], "[]")
        self.assertEqual(result["flickr_geo_status"], "invalid_location")
        self.assertIsNone(result["latitude"])

    def test_api_status_and_identity_validation(self):
        self.assertEqual(
            response_status({"stat": "fail", "code": 2}, "geo", "001"), "no_public_location"
        )
        self.assertEqual(
            response_status({"stat": "fail", "code": 1}, "info", "001"), "photo_unavailable"
        )
        self.assertEqual(
            response_status({"stat": "ok", "photo": {"id": "002"}}, "info", "001"), "failed"
        )

    def test_resume_uses_cached_success_without_api_calls(self):
        for endpoint in ("info", "geo", "comments"):
            self.put(endpoint, {})

        def unexpected(*args):
            self.fail("Cached response fetched again")

        self.assertEqual(refresh(["001"], self.cache, "unused", 3, unexpected), 0)

    def test_local_review_snapshot_requires_its_supplied_checksum(self):
        raw = b"source_provider,metadata.flickr_photo_id\nflickr,001\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.csv.gz"
            path.write_bytes(gzip.compress(raw))
            self.assertEqual(
                load_reviews(path, hashlib.sha256(raw).hexdigest()),
                [{"source_provider": "flickr", "metadata.flickr_photo_id": "001"}],
            )
            with self.assertRaises(ValueError):
                load_reviews(path, "0" * 64)

    def test_csv_parquet_roundtrip_and_no_suffix_columns(self):
        rows = build_rows(self.source, [self.review], self.cache)
        with tempfile.TemporaryDirectory() as temp:
            result = write_outputs(rows, Path(temp), {})
            frame = pl.read_parquet(Path(temp) / "joined_images.parquet")
            self.assertEqual(frame["flickr_photo_id"].to_list(), ["001", "002"])
            self.assertFalse(any(c.endswith(("_x", "_y")) for c in frame.columns))
            self.assertEqual(result["counts"]["reviewed"], 1)

    def test_retry_budget_and_restart(self):
        responses = iter([{"stat": "fail", "code": 105}, {"stat": "ok", "photo": {"id": "001"}}])
        with patch("tools.join_flickr_reviews.time.sleep"):
            self.assertEqual(
                refresh(["001"], self.cache, "unused", 2, lambda *args: next(responses)), 2
            )
        self.assertEqual(
            self.cache.execute("SELECT status FROM responses WHERE endpoint='info'").fetchone()[0],
            "ok",
        )
        self.assertEqual(self.cache.execute("SELECT count(*) FROM calls").fetchone()[0], 2)

    def test_shared_hourly_budget_and_redacted_errors(self):
        import time

        self.cache.executemany("INSERT INTO calls VALUES (?)", [(time.time(),)] * 3500)
        self.cache.commit()
        self.assertEqual(
            refresh(["001"], self.cache, "unused", 2, lambda *args: self.fail("Budget exceeded")), 0
        )
        self.cache.execute("DELETE FROM calls")
        self.cache.commit()

        def failure(*args):
            raise RuntimeError("SECRET_API_KEY_IN_URL")

        with patch("tools.join_flickr_reviews.time.sleep"):
            refresh(["001"], self.cache, "unused", 1, failure)
        payload = self.cache.execute("SELECT payload FROM responses").fetchone()[0]
        self.assertNotIn("SECRET", payload)


if __name__ == "__main__":
    unittest.main()
