"""Optional integration suite. Supply only VERITAXA_SYNTHETIC_DSN, never admin credentials."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import psycopg
import pytest

from benchmarks.export_database import seed_campaign, synthetic_dsn
from tools.common import AdminError
from tools.export_reviews import (
    BULKY_COLUMNS,
    export_reviews,
    export_schema,
    iter_export_records,
)
from tools.tabular_output import _check_record

pytestmark = pytest.mark.skipif(
    not os.environ.get("VERITAXA_SYNTHETIC_DSN"), reason="Disposable local database not configured"
)


@pytest.fixture(scope="module")
def dsn():
    value = synthetic_dsn()
    with psycopg.connect(value) as connection:
        # Refuse existing IDs; never replace unknown fixture data.
        seed_campaign(connection, 17)
        seed_campaign(connection, 2001)
    yield value
    with psycopg.connect(value) as connection:
        connection.execute("""delete from public.image_reviews where item_id in (
            select item.id from public.review_items item join public.review_batches batch
            on item.batch_id = batch.id where batch.campaign_id in (17, 2001))""")
        connection.execute("""delete from public.review_items where batch_id in (
            select id from public.review_batches where campaign_id in (17, 2001))""")
        connection.execute("delete from public.review_batches where campaign_id in (17, 2001)")
        connection.execute("delete from public.review_campaigns where id in (17, 2001)")


@pytest.fixture
def tracked_connections(monkeypatch: pytest.MonkeyPatch):
    connect = psycopg.connect
    connections = []

    def capture(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr("tools.export_reviews.psycopg.connect", capture)
    return connections


@pytest.mark.parametrize("consensus", [False, True])
@pytest.mark.parametrize("lean", [False, True])
@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_real_driver_output_matches_columns_metadata_votes_and_projection(
    dsn: str, tmp_path: Path, consensus: bool, lean: bool, suffix: str
) -> None:
    output = tmp_path / f"result.{suffix}"
    count = export_reviews(dsn, "SYNTH-17", output, consensus=consensus, derived=True, lean=lean)
    schema = export_schema(consensus=consensus, derived=True, lean=lean)
    frame = pl.read_csv(output, schema=schema) if suffix == "csv" else pl.read_parquet(output)
    assert frame.schema == schema
    assert count == (17 if consensus else 38)
    assert frame.height == count
    first_image = frame.filter(pl.col("image_id") == "synthetic-1")
    first = first_image.row(0, named=True)
    if lean:
        assert BULKY_COLUMNS.isdisjoint(frame.columns)
    else:
        assert first["source_labels"] == '{"Unicode":"🦋","nested":[null,true,""]}'
        metadata = {
            "ordinal": 1,
            "payload": hashlib.md5(b"1", usedforsecurity=False).hexdigest() * 640,
            "nested": [{"name": "🦋", "value": 0.25}],
        }
        assert first["pipeline_metadata"] == json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    common = {
        "campaign_code": "SYNTH-17",
        "target_scientific_name": "Papilio exemplaris",
        "batch_code": "SYNTH-17-0999",
        "image_id": "synthetic-1",
        "source_provider": "synthetic",
        "source_record_id": "1",
        "image_url": "https://images.example.invalid/1.jpg",
        "display_url": None,
        "flickr_search_term": None,
        "schema_version": "veritaxa-review-label-v3",
        "matches_flickr_keyword": False,
        "matches_target_scientific_name": False,
        "is_insecta_positive": False,
        "is_lepidoptera_evidence": False,
        "is_butterfly_positive": False,
        "is_butterfly_hard_negative": False,
    }
    assert {key: first[key] for key in common} == common
    if consensus:
        assert first["human_label"] == "bird"
        assert first["review_count"] == 2
        assert first["consensus_tied"] is True
        assert first["excluded_from_automatic_training"] is True
        assert datetime.fromisoformat(first["reviewed_at"]) == datetime(
            2026, 9, 10, 0, 0, 2, tzinfo=UTC
        )
        assert first_image.height == 1
        assert frame.filter(pl.col("image_id") == "synthetic-2")["human_label"].to_list() == [
            "adult_butterfly"
        ]
        assert frame.filter(pl.col("image_id") == "synthetic-4")["reviews_unanimous"].to_list() == [
            True
        ]
    else:
        assert first_image["human_label"].to_list() == ["plant", "bird"]
        assert first_image["comment"].to_list() == [None, "Synthetic comment 🦋"]
        assert {
            key: first[key]
            for key in (
                "flickrKeyword",
                "scientificName",
                "reviewer_uuid",
                "identifiedBy",
                "client_version",
                "excluded_from_automatic_training",
            )
        } == {
            "flickrKeyword": None,
            "scientificName": None,
            "reviewer_uuid": "10000000-0000-0000-0000-000000000001",
            "identifiedBy": "Synthetic reviewer 1",
            "client_version": "synthetic-client",
            "excluded_from_automatic_training": False,
        }
        assert datetime.fromisoformat(first["reviewed_at"]) == datetime(
            2026, 9, 10, 0, 0, 1, tzinfo=UTC
        )


def test_real_raw_and_consensus_order_contracts_are_distinct(dsn: str) -> None:
    with closing(iter_export_records(dsn, "SYNTH-2001", lean=True)) as records:
        raw = [(row["batch_code"], row["image_id"], row["reviewer_uuid"]) for row in records]
    assert raw == sorted(
        raw,
        key=lambda row: (
            -int(str(row[0]).rsplit("-", 1)[1]),
            int(str(row[1]).rsplit("-", 1)[1]),
            row[2],
        ),
    )
    with closing(iter_export_records(dsn, "SYNTH-2001", consensus=True, lean=True)) as records:
        consensus = [(row["campaign_code"], row["batch_code"], row["image_id"]) for row in records]
    assert consensus == sorted(consensus)
    assert consensus[0][2] == "synthetic-2001"
    assert len(consensus) == 2001


def test_real_transaction_is_read_only_and_repeatable_read(
    dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "tools.export_reviews.export_query",
        lambda **_: (
            "select %s, %s, current_setting('transaction_read_only'), "
            "current_setting('transaction_isolation')",
            ["schema_version", "campaign_code", "reviewed_at", "image_id"],
        ),
    )
    rows = list(iter_export_records(dsn, "SYNTH"))
    assert len(rows) == 1
    assert rows[0] == {
        "schema_version": "veritaxa-review-label-v3",
        "campaign_code": "SYNTH",
        "reviewed_at": "on",
        "image_id": "repeatable read",
    }


def test_real_stream_cancellation_closes_connection(dsn: str, tracked_connections) -> None:
    with closing(iter_export_records(dsn, "SYNTH-17")) as records:
        next(records)
    assert tracked_connections[0].closed


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_real_stream_slow_writer_failure_keeps_completed_output(
    dsn: str, tmp_path: Path, suffix: str, monkeypatch: pytest.MonkeyPatch, tracked_connections
) -> None:
    output = tmp_path / f"complete.{suffix}"
    export_reviews(dsn, "SYNTH-17", output)
    previous = output.read_bytes()
    checked = 0

    def interrupted(record, schema):
        nonlocal checked
        checked += 1
        if checked % 200 == 0:
            time.sleep(0.005)  # Exercise backpressure without queuing another application batch.
        if checked == 1001:  # Past several real Parquet flushes, not just writer initialization.
            raise OSError("Synthetic late writer failure")
        return _check_record(record, schema)

    monkeypatch.setattr("tools.tabular_output._check_record", interrupted)
    with pytest.raises(OSError, match="Synthetic late writer failure"):
        export_reviews(dsn, "SYNTH-2001", output)
    assert output.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [output]
    assert all(connection.closed for connection in tracked_connections)


def test_concurrent_edit_does_not_change_an_active_export_snapshot(dsn: str) -> None:
    review_id = (2001 * 1000000 + 2001) * 10 + 1
    try:
        with closing(iter_export_records(dsn, "SYNTH-2001", lean=True)) as records:
            next(records)
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    "update public.image_reviews set comment = 'Synthetic concurrent edit' "
                    "where id = %s",
                    (review_id,),
                )
            last_item = [row for row in records if row["image_id"] == "synthetic-2001"]
        assert last_item[0]["comment"] is None
        with closing(iter_export_records(dsn, "SYNTH-2001", lean=True)) as records:
            updated = next(row for row in records if row["image_id"] == "synthetic-2001")
        assert updated["comment"] == "Synthetic concurrent edit"
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "update public.image_reviews set comment = null where id = %s", (review_id,)
            )


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
@pytest.mark.parametrize("payload_mib", [8, 17])
def test_real_driver_large_row_policy(
    dsn: str, tmp_path: Path, suffix: str, payload_mib: int, tracked_connections
) -> None:
    item_id = 17 * 1000000 + 17  # Late row: earlier records may already have been written.
    with psycopg.connect(dsn) as connection:
        original = connection.execute(
            "select pipeline_metadata from public.review_items where id = %s", (item_id,)
        ).fetchone()[0]
        connection.execute(
            "update public.review_items set pipeline_metadata = "
            "jsonb_build_object('payload', repeat('x', %s)) where id = %s",
            (payload_mib * 1024 * 1024, item_id),
        )
    output = tmp_path / f"result.{suffix}"
    try:
        if payload_mib > 16:
            with pytest.raises(AdminError, match="16 MiB"):
                export_reviews(dsn, "SYNTH-17", output)
            assert list(tmp_path.iterdir()) == []
            # Explicit lean projection is not decoded and discarded in Python.
            assert export_reviews(dsn, "SYNTH-17", output, lean=True) == 38
        else:
            assert export_reviews(dsn, "SYNTH-17", output) == 38
            schema = export_schema()
            frame = (
                pl.read_csv(output, schema=schema) if suffix == "csv" else pl.read_parquet(output)
            )
            values = frame.filter(pl.col("image_id") == "synthetic-17")["pipeline_metadata"]
            assert all(len(json.loads(value)["payload"]) == 8 * 1024 * 1024 for value in values)
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "update public.review_items set pipeline_metadata = %s where id = %s",
                (psycopg.types.json.Jsonb(original), item_id),
            )
    assert all(connection.closed for connection in tracked_connections)
