import json
import unittest

import polars as pl

from tools.join_flickr_reviews import build_rows, open_cache
from tools.queue_flickr_enrichment import seed_queue


class EnrichmentQueueTests(unittest.TestCase):
    def test_deduplicates_collections_prioritizes_geotagged_and_reuses_success(self):
        cache = open_cache(":memory:")
        cache.execute("INSERT INTO responses VALUES ('same','info','ok','{}','2026-11-11')")
        seed_queue(cache, ["same", "geo"], ["same", "old"])
        rows = cache.execute(
            "SELECT photo_id,endpoint,priority,state FROM combined_enrichment_queue"
        ).fetchall()
        self.assertEqual(len(rows), 6)
        self.assertIn(("same", "info", 0, "complete"), rows)
        self.assertIn(("old", "comments", 1, "pending"), rows)
        self.assertEqual({r[1] for r in rows}, {"info", "comments"})
        seed_queue(cache, ["same", "geo"], ["same", "old"])
        self.assertEqual(
            cache.execute("SELECT count(*) FROM combined_enrichment_queue").fetchone()[0], 6
        )
        cache.close()

    def test_metadata_only_refresh_preserves_discovery_geotags(self):
        cache = open_cache(":memory:")
        source = pl.DataFrame(
            {
                "source": ["flickr"],
                "flickr_photo_id": ["geo"],
                "latitude": [0.0],
                "longitude": [20.0],
                "accuracy": [16],
            }
        )
        rows = build_rows(source, [], cache)
        self.assertEqual(rows[0]["latitude"], 0)
        self.assertEqual(rows[0]["longitude"], 20)
        self.assertEqual(rows[0]["geolocation_source"], "flickr.photos.search")
        self.assertEqual(json.loads(rows[0]["first_round_reviews_json"]), [])
        cache.close()


if __name__ == "__main__":
    unittest.main()
