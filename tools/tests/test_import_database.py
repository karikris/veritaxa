"""Optional integration tests: only an explicitly named disposable import database."""

from __future__ import annotations

import os
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import polars as pl
import psycopg
import pytest

from benchmarks.import_database import import_dsn, remove_campaign
from tools.candidate_rows import candidate_from_row
from tools.candidate_spool import validate_candidates
from tools.common import AdminError
from tools.import_candidates import import_file
from tools.import_publish import import_spec, publish_candidates
from tools.tests.test_candidate_input import source_rows

pytestmark = pytest.mark.skipif(
    not os.environ.get("VERITAXA_IMPORT_DSN"), reason="Disposable import database not configured"
)


@pytest.fixture
def campaign():
    dsn = import_dsn()
    code = "SYNTH-TEST-" + uuid4().hex
    spec = import_spec(
        campaign_code=code,
        internal_name="Synthetic test",
        reviewer_name="Synthetic",
        batch_prefix=code,
        target_scientific_name="Papilio exemplaris",
        batch_size=37,
        status="open",
    )
    yield dsn, spec
    with psycopg.connect(dsn) as connection:
        remove_campaign(connection, code)


def database_rows(dsn, code):
    with psycopg.connect(dsn) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """select batch.position as batch_position, item.position as item_position,
                item.image_id, item.image_url, item.display_url, item.source_provider,
                item.source_record_id, item.source_page_url, item.flickr_search_term,
                item.source_labels, item.pipeline_metadata
                from public.review_items item
                join public.review_batches batch on batch.id=item.batch_id
                join public.review_campaigns campaign on campaign.id=batch.campaign_id
                where campaign.campaign_code=%s order by batch.position, item.position""",
                (code,),
            )
            return cursor.fetchall()


@pytest.mark.parametrize("method", ["pipeline", "copy"])
@pytest.mark.parametrize("file_format", ["csv", "parquet", "ndjson"])
@pytest.mark.parametrize("shuffle_seed", [None, 0])
def test_complete_import_preserves_values_positions_and_declared_shuffle(
    campaign, tmp_path: Path, method: str, file_format: str, shuffle_seed: int | None, monkeypatch
):
    dsn, spec = campaign
    path = tmp_path / f"input.{file_format}"
    frame = pl.DataFrame(source_rows(151))
    getattr(frame, f"write_{file_format}")(path)
    # Small chunks must not turn into extra visible review batches.
    monkeypatch.setattr("tools.candidate_spool.MAX_CHUNK_BYTES", 1200)
    counts = import_file(path, spec, database=lambda: dsn, method=method, shuffle_seed=shuffle_seed)
    assert counts == (1, 5, 151)
    actual = database_rows(dsn, spec.campaign_code)
    candidates = {
        row["image_id"]: asdict(candidate_from_row(row)) for row in frame.iter_rows(named=True)
    }
    for index, row in enumerate(actual):
        assert row.pop("batch_position") == index // 37 + 1
        assert row.pop("item_position") == index % 37 + 1
        assert row == candidates[row["image_id"]]
    ids = [row["image_id"] for row in actual]
    if shuffle_seed is None:
        assert ids == frame["image_id"].to_list()
    else:
        with validate_candidates(
            frame.iter_rows(named=True), batch_size=37, shuffle_seed=0
        ) as spool:
            expected = [
                candidate.image_id for chunk in spool.chunks() for candidate in chunk.candidates
            ]
        assert ids == expected
        assert ids != frame["image_id"].to_list()
    with psycopg.connect(dsn) as connection:
        state = connection.execute(
            """select campaign.status::text, bool_and(batch.status='open'),
            bool_and(batch.opened_at is not null) from public.review_campaigns campaign
            join public.review_batches batch on batch.campaign_id=campaign.id
            where campaign.campaign_code=%s group by campaign.status""",
            (spec.campaign_code,),
        ).fetchone()
        assert state == ("open", True, True)


@pytest.mark.parametrize("method", ["pipeline", "copy"])
@pytest.mark.parametrize("failure", ["stream", "constraint", "count"])
def test_late_insert_failure_rolls_back_all_batches_and_campaign(
    campaign, method: str, failure: str
):
    dsn, spec = campaign
    with validate_candidates(source_rows(151), batch_size=37) as spool:

        def failing_chunks():
            for chunk in spool.chunks():
                if chunk.batch_position == 3:
                    if failure == "stream":
                        raise OSError("Synthetic late spool failure")
                    if failure == "constraint":
                        # Force a genuine Postgres duplicate after earlier batches were sent.
                        with psycopg.connect(dsn) as observer:
                            assert observer.execute(
                                "select count(*) from public.review_campaigns "
                                "where campaign_code=%s",
                                (spec.campaign_code,),
                            ).fetchone() == (0,)
                        duplicate = replace(
                            chunk.candidates[1], image_id=chunk.candidates[0].image_id
                        )
                        chunk = replace(
                            chunk,
                            candidates=(chunk.candidates[0], duplicate, *chunk.candidates[2:]),
                        )
                yield chunk

        expected_error = {
            "stream": OSError,
            "constraint": psycopg.errors.UniqueViolation,
            "count": AdminError,
        }[failure]
        with (
            closing(failing_chunks()) as chunks,
            pytest.raises(expected_error),
        ):
            publish_candidates(
                spec,
                chunks,
                dsn,
                expected_batches=5,
                expected_items=152 if failure == "count" else 151,
                method=method,
            )
    assert database_rows(dsn, spec.campaign_code) == []
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "select count(*) from public.review_campaigns where campaign_code=%s",
            (spec.campaign_code,),
        ).fetchone() == (0,)
