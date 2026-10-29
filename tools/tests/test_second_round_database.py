"""Verify category replacement and round-two saves through the browser RPCs."""

from __future__ import annotations

import json
from uuid import uuid4

from tools.create_rereview_round import publication_sql
from tools.tests.test_rereview_database import fixture as fixture
from tools.tests.test_rereview_database import pytestmark as pytestmark


def test_replacement_archives_old_round_and_preserves_first_round(fixture):
    connection, _, _, original_batch = fixture
    connection.execute(publication_sql("SYNTH-OLD"))
    connection.execute("drop table rereview_votes, rereview_members, rereview_original_versions")
    connection.execute(publication_sql("SYNTH-NEW", replace_existing=True))
    assert connection.execute(
        """select campaign.status::text, batch.status::text, count(item.id)
        from public.review_campaigns campaign
        join public.review_batches batch on batch.campaign_id = campaign.id
        join public.review_items item on item.batch_id = batch.id
        where campaign.campaign_code ~ '^REREVIEW-SYNTH-OLD-[0-9]+$'
        group by campaign.status, batch.status"""
    ).fetchall() == [("archived", "archived", 1005)]
    assert connection.execute(
        """select batch.reviewer_name, count(item.id)
        from public.review_batches batch
        join public.review_campaigns campaign on campaign.id = batch.campaign_id
        join public.review_items item on item.batch_id = batch.id
        where campaign.campaign_code ~ '^REREVIEW-SYNTH-NEW-[0-9]+$'
          and batch.status = 'open' and campaign.status = 'open'
        group by batch.id"""
    ).fetchall() == [("Round 2: Moth", 1005)]
    assert connection.execute(
        "select count(*), count(second_round_label), min(label::text) "
        "from public.image_reviews where item_id in "
        "(select id from public.review_items where batch_id = %s)",
        (original_batch,),
    ).fetchone() == (1005, 0, "moth")


def test_round_two_save_retry_and_correction_keep_original_answers(fixture):
    connection, reviewer, _, original_batch = fixture
    connection.execute(publication_sql("SYNTH-SECOND"))
    item_id, batch_id = connection.execute(
        """select item.id, item.batch_id from public.review_items item
        where item.pipeline_metadata->'_veritaxa_rereview'->>'round_code' = 'SYNTH-SECOND'
        order by item.position limit 1"""
    ).fetchone()
    connection.execute("set local role authenticated")
    connection.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (json.dumps({"sub": str(reviewer), "role": "authenticated"}),),
    )
    submission_id = uuid4()
    for _ in range(2):
        connection.execute(
            "select * from public.save_image_review_v2(%s, 'bird', null, %s, 'synthetic', 0)",
            (item_id, submission_id),
        ).fetchall()
    assert connection.execute(
        "select reviewed_count, total_count from public.list_review_batches() where batch_id = %s",
        (batch_id,),
    ).fetchone() == (1, 1005)
    connection.execute("reset role")
    assert connection.execute(
        "select label::text, second_round_label::text, version "
        "from public.image_reviews where item_id = %s",
        (item_id,),
    ).fetchone() == ("bird", "bird", 1)

    connection.execute("set local role authenticated")
    connection.execute(
        "select * from public.save_image_review_v2(%s, 'target_scientific_name', "
        "null, %s, 'synthetic', 1)",
        (item_id, uuid4()),
    ).fetchall()
    assert connection.execute(
        "select current_label::text, current_version "
        "from public.get_review_cursor(%s, 2, 'previous')",
        (batch_id,),
    ).fetchone() == ("target_scientific_name", 2)
    connection.execute("reset role")
    assert connection.execute(
        'select second_round_label::text, "scientificName", version '
        "from public.image_reviews where item_id = %s",
        (item_id,),
    ).fetchone() == ("target_scientific_name", "Taxon example", 2)
    assert connection.execute(
        "select count(*), count(second_round_label), min(label::text) "
        "from public.image_reviews where item_id in "
        "(select id from public.review_items where batch_id = %s)",
        (original_batch,),
    ).fetchone() == (1005, 0, "moth")
