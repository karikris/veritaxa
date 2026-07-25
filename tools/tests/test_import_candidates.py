from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from tools.common import AdminError
from tools.import_candidates import (
    build_import_plan,
    import_plan,
    main,
    read_candidate_frame,
)


def candidate_rows(count: int) -> list[dict[str, Any]]:
    return [
        {
            "image_id": f"synthetic-{index:04d}",
            "image_url": f"https://images.example.invalid/{index:04d}.jpg",
            "display_url": f"https://images.example.invalid/{index:04d}-small.jpg",
            "source_provider": "synthetic",
            "flickr_labels_json": json.dumps({"synthetic_label": index}),
            "model_score": index / max(count, 1),
        }
        for index in range(count)
    ]


def plan(frame: pl.DataFrame, **overrides: Any):
    arguments = {
        "campaign_code": "SYNTH-2026-001",
        "internal_name": "Synthetic test campaign",
        "reviewer_name": "Synthetic candidate review",
        "batch_prefix": "SYNTH",
    }
    arguments.update(overrides)
    return build_import_plan(frame, **arguments)


@pytest.mark.parametrize("suffix", [".parquet", ".csv", ".ndjson"])
def test_reads_supported_input_formats(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"candidates{suffix}"
    frame = pl.DataFrame(candidate_rows(3))
    if suffix == ".parquet":
        frame.write_parquet(path)
    elif suffix == ".csv":
        frame.write_csv(path)
    else:
        frame.write_ndjson(path)

    imported = read_candidate_frame(path)

    assert imported.height == 3
    assert {"image_id", "image_url", "source_provider"} <= set(imported.columns)


def test_splits_batches_at_one_thousand_and_preserves_order() -> None:
    result = plan(pl.DataFrame(candidate_rows(1001)))

    assert [len(batch.candidates) for batch in result.batches] == [1000, 1]
    assert [batch.code for batch in result.batches] == ["SYNTH-001", "SYNTH-002"]
    assert result.batches[0].candidates[0].image_id == "synthetic-0000"
    assert result.batches[1].candidates[0].image_id == "synthetic-1000"


def test_rejects_duplicate_image_ids_within_a_batch() -> None:
    rows = candidate_rows(2)
    rows[1]["image_id"] = rows[0]["image_id"]

    with pytest.raises(AdminError, match="Duplicate image IDs"):
        plan(pl.DataFrame(rows))


@pytest.mark.parametrize(
    "url",
    [
        "http://images.example.invalid/image.jpg",
        "https://user:password@images.example.invalid/image.jpg",
        "not-a-url",
    ],
)
def test_rejects_invalid_image_urls(url: str) -> None:
    rows = candidate_rows(1)
    rows[0]["image_url"] = url

    with pytest.raises(AdminError, match=r"credential-free HTTPS|must be an HTTPS"):
        plan(pl.DataFrame(rows))


def test_dry_run_validates_without_opening_a_database(tmp_path: Path, capsys: Any) -> None:
    path = tmp_path / "candidates.parquet"
    pl.DataFrame(candidate_rows(2)).write_parquet(path)

    result = main(
        [
            "--input",
            str(path),
            "--campaign-code",
            "SYNTH-2026-001",
            "--internal-name",
            "Synthetic test campaign",
            "--reviewer-name",
            "Synthetic candidate review",
            "--batch-prefix",
            "SYNTH",
            "--dry-run",
        ]
    )

    assert result == 0
    assert capsys.readouterr().out == "Dry run valid: campaigns=1 batches=1 items=2\n"


class FailingCursor:
    def __init__(self) -> None:
        self.fetch_count = 0

    def __enter__(self) -> FailingCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _query: str, _parameters: object) -> None:
        return None

    def fetchone(self) -> tuple[str]:
        self.fetch_count += 1
        return (f"00000000-0000-0000-0000-{self.fetch_count:012d}",)

    def executemany(self, _query: str, _parameters: object) -> None:
        raise RuntimeError("synthetic insertion failure")


class FailingConnection:
    def __init__(self) -> None:
        self.rolled_back = False

    def __enter__(self) -> FailingConnection:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.rolled_back = _type is not None

    def cursor(self) -> FailingCursor:
        return FailingCursor()


def test_insertion_failure_rolls_back_the_transaction() -> None:
    connection = FailingConnection()
    import_data = plan(pl.DataFrame(candidate_rows(1)))

    with pytest.raises(RuntimeError, match="synthetic insertion failure"):
        import_plan(
            import_data,
            "postgres" + "ql://unused",
            connect=lambda _dsn: connection,  # type: ignore[arg-type]
        )

    assert connection.rolled_back is True
