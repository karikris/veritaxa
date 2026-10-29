"""Exercise publication and regrouping on an explicitly disposable local database."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import psycopg
import pytest

from benchmarks.export_database import synthetic_dsn
from tools.create_rereview_round import publication_sql, regroup_sql, snapshot_query

pytestmark = pytest.mark.skipif(
    not os.environ.get("VERITAXA_SYNTHETIC_DSN"), reason="Disposable local database not configured"
)


@pytest.fixture
def fixture():
    connection = psycopg.connect(synthetic_dsn())
    reviewer, campaign, batch = (uuid4() for _ in range(3))
    connection.execute(
        "insert into auth.users(id, raw_user_meta_data) values (%s, %s)",
        (reviewer, '{"identified_by":"Synthetic folder reviewer"}'),
    )
    connection.execute(
        """insert into public.review_campaigns
        (id, internal_name, reviewer_name, campaign_code, target_scientific_name, status)
        values (%s, 'Synthetic folders', 'Synthetic folders', %s, 'Taxon example', 'closed')""",
        (campaign, f"SYNTH-{campaign}"),
    )
    connection.execute(
        """insert into public.review_batches
        (id, campaign_id, batch_code, reviewer_name, position, status)
        values (%s, %s, %s, 'Synthetic folders', 1, 'closed')""",
        (batch, campaign, f"SYNTH-{batch}"),
    )
    connection.execute(
        """insert into public.review_items
        (batch_id, position, image_id, source_provider, image_url, pipeline_metadata)
        select %s, n, 'synthetic-folder-' || n, 'synthetic',
          'https://images.example.invalid/folder.svg', jsonb_build_object('ordinal', n)
        from generate_series(1, 1005) n""",
        (batch,),
    )
    connection.execute(
        """insert into public.image_reviews
        (item_id, reviewer_id, label, submission_id, client_version, "identifiedBy")
        select id, %s, 'moth', gen_random_uuid(), 'synthetic-folders', 'Synthetic folder reviewer'
        from public.review_items where batch_id = %s""",
        (reviewer, batch),
    )
    try:
        yield connection, reviewer, campaign, batch
    finally:
        connection.rollback()
        connection.close()


def publish(connection):
    connection.execute(publication_sql("SYNTH-FOLDERS"))
    return connection.execute(
        """select batch.id, batch.campaign_id from public.review_batches batch
        join public.review_campaigns campaign on campaign.id = batch.campaign_id
        where campaign.campaign_code ~ '^REREVIEW-SYNTH-FOLDERS-[0-9]+$'"""
    ).fetchone()


def split_folder(connection, first_batch, campaign):
    """Reproduce the old 1,000-image split while retaining the published IDs."""
    second_batch = uuid4()
    connection.execute(
        """insert into public.review_batches
        (id, campaign_id, batch_code, reviewer_name, position, status)
        values (%s, %s, 'RR-SYNTH-FOLDERS-001-002', 'Synthetic old batch', 2, 'open')""",
        (second_batch, campaign),
    )
    connection.execute(
        """update public.review_items set batch_id = %s, position = position - 1000
        where batch_id = %s and position > 1000""",
        (second_batch, first_batch),
    )
    return second_batch


def test_whole_option_exceeds_old_limit_and_excludes_later_round_votes(fixture):
    connection, reviewer, _, _ = fixture
    first_batch, _ = publish(connection)
    assert connection.execute(
        "select count(*), max(position) from public.review_items where batch_id = %s",
        (first_batch,),
    ).fetchone() == (1005, 1005)
    connection.execute(
        """insert into public.image_reviews
        (item_id, reviewer_id, label, submission_id, client_version, "identifiedBy")
        select id, %s, 'bird', gen_random_uuid(), 'synthetic-folders', 'Synthetic folder reviewer'
        from public.review_items where batch_id = %s and position = 1""",
        (reviewer, first_batch),
    )
    connection.execute("drop table rereview_votes, rereview_members, rereview_original_versions")
    connection.execute(publication_sql("SYNTH-NEXT"))
    assert connection.execute(
        """select count(distinct batch.id), count(item.id),
          min(item.pipeline_metadata->'_veritaxa_rereview'->>'category')
        from public.review_batches batch
        join public.review_campaigns campaign on campaign.id = batch.campaign_id
        join public.review_items item on item.batch_id = batch.id
        where campaign.campaign_code like 'REREVIEW-SYNTH-NEXT-%'"""
    ).fetchone() == (1, 1005, "moth")


def test_regroup_preserves_reviews_provenance_and_cursor_progress(fixture):
    connection, reviewer, _, original_batch = fixture
    first_batch, campaign = publish(connection)
    second_batch = split_folder(connection, first_batch, campaign)
    connection.execute(
        """insert into public.image_reviews
        (item_id, reviewer_id, label, comment, submission_id, client_version, "identifiedBy")
        select id, %s, 'plant', 'Synthetic saved correction', gen_random_uuid(),
          'synthetic-folders', 'Synthetic folder reviewer'
        from public.review_items where batch_id = %s and position = 1""",
        (reviewer, second_batch),
    )
    reviews = connection.execute(
        "select id, to_jsonb(r) from public.image_reviews r order by id"
    ).fetchall()
    contents = connection.execute(
        "select id, to_jsonb(i) - 'batch_id' - 'position' from public.review_items i order by id"
    ).fetchall()
    originals = connection.execute(
        "select id, to_jsonb(i) from public.review_items i where batch_id = %s order by id",
        (original_batch,),
    ).fetchall()
    connection.execute(regroup_sql("SYNTH-FOLDERS"))
    assert connection.execute(
        "select count(*), min(position), max(position) from public.review_items where batch_id=%s",
        (first_batch,),
    ).fetchone() == (1005, 1, 1005)
    assert connection.execute(
        "select status::text from public.review_batches where id = %s", (second_batch,)
    ).fetchone() == ("closed",)
    assert (
        reviews
        == connection.execute(
            "select id, to_jsonb(r) from public.image_reviews r order by id"
        ).fetchall()
    )
    assert (
        contents
        == connection.execute(
            "select id, to_jsonb(i) - 'batch_id' - 'position' "
            "from public.review_items i order by id"
        ).fetchall()
    )
    assert (
        originals
        == connection.execute(
            "select id, to_jsonb(i) from public.review_items i where batch_id = %s order by id",
            (original_batch,),
        ).fetchall()
    )

    connection.execute("set local role authenticated")
    connection.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (json.dumps({"sub": str(reviewer), "role": "authenticated"}),),
    )
    assert connection.execute(
        "select reviewed_count, total_count from public.list_review_batches() where batch_id = %s",
        (first_batch,),
    ).fetchone() == (1, 1005)
    assert connection.execute(
        "select position from public.get_review_cursor(%s, 1000, 'next')", (first_batch,)
    ).fetchone() == (1001,)
    assert connection.execute(
        "select current_label::text, current_comment "
        "from public.get_review_cursor(%s, 1000, 'next')",
        (first_batch,),
    ).fetchone() == ("plant", "Synthetic saved correction")
    connection.execute("reset role")

    # A repeat administration command should perform no further writes.
    locations = connection.execute(
        "select id, ctid::text from public.review_items order by id"
    ).fetchall()
    connection.execute("drop table regroup_members, regroup_original_versions")
    connection.execute(regroup_sql("SYNTH-FOLDERS"))
    assert (
        locations
        == connection.execute(
            "select id, ctid::text from public.review_items order by id"
        ).fetchall()
    )


def test_round_prefix_does_not_select_or_move_another_round(fixture):
    connection, _, _, _ = fixture
    connection.execute(publication_sql("SYNTH-FOLDERS-EXTRA"))
    connection.execute("drop table rereview_votes, rereview_members, rereview_original_versions")
    first_batch, campaign = publish(connection)
    assert len(connection.execute(snapshot_query("SYNTH-FOLDERS")).fetchall()) == 1005
    other_round = connection.execute(snapshot_query("SYNTH-FOLDERS-EXTRA")).fetchall()
    split_folder(connection, first_batch, campaign)
    connection.execute(regroup_sql("SYNTH-FOLDERS"))
    assert other_round == connection.execute(snapshot_query("SYNTH-FOLDERS-EXTRA")).fetchall()


@pytest.mark.parametrize("invalid", ["missing", "mixed", "closed", "duplicate"])
def test_regroup_rejects_invalid_round_without_partial_moves(fixture, invalid):
    connection, _, _, _ = fixture
    first_batch, campaign = publish(connection)
    second_batch = split_folder(connection, first_batch, campaign)
    if invalid == "missing":
        connection.execute(
            """update public.review_items set pipeline_metadata = '{}'
            where batch_id = %s and position = 1""",
            (second_batch,),
        )
    elif invalid == "mixed":
        connection.execute(
            """update public.review_items set pipeline_metadata = jsonb_set(
              pipeline_metadata, '{_veritaxa_rereview,category}', '"plant"')
            where batch_id = %s and position = 1""",
            (second_batch,),
        )
    elif invalid == "closed":
        connection.execute(
            "update public.review_campaigns set status='closed' where id=%s", (campaign,)
        )
    else:
        connection.execute(
            """update public.review_items set image_id = (
              select image_id from public.review_items where batch_id = %s and position = 1)
            where batch_id = %s and position = 1""",
            (first_batch, second_batch),
        )
    before = connection.execute(
        "select id, to_jsonb(i) from public.review_items i order by id"
    ).fetchall()
    with pytest.raises(psycopg.errors.RaiseException), connection.transaction():
        connection.execute(regroup_sql("SYNTH-FOLDERS"))
    assert (
        before
        == connection.execute(
            "select id, to_jsonb(i) from public.review_items i order by id"
        ).fetchall()
    )
