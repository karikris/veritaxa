import copy

import pytest

from tools.attach_location_clues import attach_one, merge_metadata
from tools.common import AdminError
from tools.location_clue_groups import METADATA_KEY


def fixture():
    row = {
        "id": "synthetic-item",
        "batch_id": "synthetic-batch",
        "source_provider": "synthetic",
        "source_record_id": "synthetic-photo",
        "pipeline_metadata": {"model": {"score": 0.5}},
    }
    plan = {
        "item_id": row["id"],
        "source_provider": row["source_provider"],
        "source_record_id": row["source_record_id"],
        "payload": {"status": "unverified"},
    }
    return row, plan


def test_merge_preserves_original_fields_and_checks_photo_identity():
    row, plan = fixture()
    before = copy.deepcopy(row)
    merged = merge_metadata(row, plan)
    assert merged == {**row["pipeline_metadata"], METADATA_KEY: plan["payload"]}
    assert row == before
    with pytest.raises(AdminError, match="identity"):
        merge_metadata(row, {**plan, "source_record_id": "another-photo"})


def test_conditional_retry_preserves_concurrent_metadata_and_is_idempotent():
    row, plan = fixture()
    original = copy.deepcopy(row)

    class Client:
        calls = 0
        live = copy.deepcopy(row)

        def request(self, method, table, params, body=None):
            assert table == "review_items"
            if method == "GET":
                return [self.live]
            assert method == "PATCH" and set(body) == {"pipeline_metadata"}
            self.calls += 1
            if self.calls == 1:
                self.live["pipeline_metadata"]["concurrent_admin_value"] = "preserved"
                return []
            self.live["pipeline_metadata"] = body["pipeline_metadata"]
            return [{"id": row["id"], "pipeline_metadata": body["pipeline_metadata"]}]

    client = Client()
    assert attach_one(client, row, plan) == "attached"
    assert client.live["pipeline_metadata"]["concurrent_admin_value"] == "preserved"
    assert row == original
    assert attach_one(client, client.live, plan) == "already_attached"
    assert client.calls == 2


def test_attachment_does_not_replace_a_human_verified_location():
    row, plan = fixture()
    row["pipeline_metadata"][METADATA_KEY] = {"status": "verified", "reviewed_by": "Synthetic A"}
    with pytest.raises(AdminError, match="adjudicated"):
        merge_metadata(row, plan)
