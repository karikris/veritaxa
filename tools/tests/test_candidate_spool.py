from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.candidate_rows import candidate_from_row
from tools.candidate_spool import validate_candidates
from tools.common import AdminError


def rows(count: int):
    for index in range(count):
        yield {
            "image_id": f"synthetic-{index}",
            "image_url": f"https://images.example.invalid/{index}.jpg",
            "source_provider": "synthetic",
            "pipeline_metadata": {"nested": [None, True, "🦋"], "collision": "original"},
            "collision": "retained extra",
            "extra_score": 0.25,
        }


def test_spool_retains_normalized_metadata_order_and_logical_positions(tmp_path: Path) -> None:
    with validate_candidates(rows(1001), temporary_parent=tmp_path) as spool:
        assert spool.item_count == 1001
        assert spool.batch_count == 2
        assert spool.shuffled is False
        chunks = list(spool.chunks())
        assert [
            (chunk.batch_position, chunk.first_position, len(chunk.candidates)) for chunk in chunks
        ] == [
            (1, 1, 1000),
            (2, 1, 1),
        ]
        assert [candidate for chunk in chunks for candidate in chunk.candidates] == [
            candidate_from_row(row) for row in rows(1001)
        ]
        directory = next(tmp_path.iterdir())
        assert directory.stat().st_mode & 0o777 == 0o700
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            spool.connection.execute("delete from candidates")
    assert list(tmp_path.iterdir()) == []


def test_byte_chunks_do_not_change_campaign_batch_boundaries(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("tools.candidate_spool.MAX_CHUNK_BYTES", 600)
    with validate_candidates(rows(5), batch_size=3, temporary_parent=tmp_path) as spool:
        chunks = list(spool.chunks())
        assert [(chunk.batch_position, chunk.first_position) for chunk in chunks] == [
            (1, 1),
            (1, 2),
            (1, 3),
            (2, 1),
            (2, 2),
        ]
        assert [len(chunk.candidates) for chunk in chunks] == [1] * 5


def test_seed_zero_uses_versioned_global_order_independent_of_chunk_size(tmp_path: Path) -> None:
    expected = [3, 9, 11, 1, 5, 6, 8, 7, 4, 10, 2, 0]
    for batch_size in (1, 5, 1000):
        with validate_candidates(
            rows(12), batch_size=batch_size, shuffle_seed=0, temporary_parent=tmp_path
        ) as spool:
            actual = [
                candidate.image_id for chunk in spool.chunks() for candidate in chunk.candidates
            ]
            assert actual == [f"synthetic-{index}" for index in expected]
    with validate_candidates(rows(12), shuffle_seed=1, temporary_parent=tmp_path) as spool:
        assert [
            candidate.image_id for chunk in spool.chunks() for candidate in chunk.candidates
        ] != actual


@pytest.mark.parametrize("shuffle_seed", [None, 0, 31])
def test_duplicates_are_checked_in_final_logical_batches_and_cleanup_on_failure(
    tmp_path: Path,
    shuffle_seed: int | None,
) -> None:
    duplicate = list(rows(1)) * 2
    with pytest.raises(AdminError, match="Duplicate image IDs"):
        with validate_candidates(
            duplicate, batch_size=2, shuffle_seed=shuffle_seed, temporary_parent=tmp_path
        ):
            pytest.fail("Validation must finish before a spool is exposed")
    assert list(tmp_path.iterdir()) == []
    with validate_candidates(
        duplicate, batch_size=1, shuffle_seed=shuffle_seed, temporary_parent=tmp_path
    ) as spool:
        assert spool.item_count == 2  # Membership in different batches remains valid.


@pytest.mark.parametrize("failure", ["source", "invalid", "consumer", "oversized"])
def test_private_spool_cleanup_on_every_failure(tmp_path: Path, monkeypatch, failure: str) -> None:
    def source():
        yield from rows(3)
        if failure == "source":
            raise OSError("Synthetic interrupted input")
        if failure == "invalid":
            yield {"image_id": "synthetic-invalid"}

    if failure == "oversized":
        monkeypatch.setattr("tools.candidate_spool.MAX_ROW_BYTES", 1)
    with pytest.raises((AdminError, OSError)):
        with validate_candidates(source(), temporary_parent=tmp_path):
            if failure == "consumer":
                raise OSError("Synthetic interrupted publication")
    assert list(tmp_path.iterdir()) == []


def test_empty_spool_has_no_batches(tmp_path: Path) -> None:
    with validate_candidates([], temporary_parent=tmp_path) as spool:
        assert (spool.item_count, spool.batch_count) == (0, 0)
        assert list(spool.chunks()) == []


@pytest.mark.parametrize("value", ['{"score":NaN}', {"score": float("inf")}])
def test_nonfinite_metadata_is_rejected_during_validation(tmp_path: Path, value: object) -> None:
    row = next(rows(1))
    row["pipeline_metadata"] = value
    with pytest.raises(AdminError, match="finite"):
        with validate_candidates([row], temporary_parent=tmp_path):
            pytest.fail("Nonfinite JSON cannot be published to Postgres")
    assert list(tmp_path.iterdir()) == []


def test_large_single_row_is_alone_without_splitting_a_logical_batch(tmp_path: Path) -> None:
    source = list(rows(3))
    source[1]["pipeline_metadata"] = {"payload": "x" * (8 * 1024 * 1024)}
    with validate_candidates(source, temporary_parent=tmp_path) as spool:
        positions = []
        for chunk in spool.chunks():
            positions.append((chunk.batch_position, chunk.first_position, len(chunk.candidates)))
        assert positions == [(1, 1, 1), (1, 2, 1), (1, 3, 1)]
