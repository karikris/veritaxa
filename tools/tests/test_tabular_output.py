from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from tools.common import AdminError
from tools.tabular_output import MAX_BATCH_BYTES, MAX_BATCH_ROWS, MAX_RECORD_BYTES, write_records

SCHEMA = pl.Schema({"text": pl.String, "count": pl.UInt32, "flag": pl.Boolean})
ROWS = [
    {"text": None, "count": 0, "flag": False},
    {"text": "", "count": 2, "flag": True},
    {"text": 'Comma, newline\nand "Unicode 🦋"', "count": 3, "flag": None},
]


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_streamed_output_preserves_types_nulls_empty_strings_and_order(
    tmp_path: Path, suffix: str
) -> None:
    output = tmp_path / f"reviews.{suffix}"
    assert write_records(iter(ROWS), SCHEMA, output) == 3
    actual = pl.read_csv(output, schema=SCHEMA) if suffix == "csv" else pl.read_parquet(output)
    assert actual.schema == SCHEMA
    assert actual.to_dicts() == ROWS
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_empty_export_retains_headers_and_schema(tmp_path: Path, suffix: str) -> None:
    output = tmp_path / f"empty.{suffix}"
    assert write_records(iter([]), SCHEMA, output) == 0
    actual = pl.read_csv(output, schema=SCHEMA) if suffix == "csv" else pl.read_parquet(output)
    assert actual.schema == SCHEMA
    assert actual.height == 0


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_late_failure_preserves_previous_output_and_removes_private_spool(
    tmp_path: Path, suffix: str
) -> None:
    output = tmp_path / f"reviews.{suffix}"
    write_records(iter(ROWS), SCHEMA, output)
    previous = output.read_bytes()

    def failing_records() -> Iterator[dict[str, object]]:
        yield ROWS[0]
        raise OSError("Synthetic interrupted source")

    with pytest.raises(OSError, match="Synthetic interrupted source"):
        write_records(failing_records(), SCHEMA, output)
    assert output.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("text", ["x" * (MAX_RECORD_BYTES + 1), "🦋" * (MAX_RECORD_BYTES // 4 + 1)])
def test_oversized_rows_are_rejected_without_publishing(tmp_path: Path, text: str) -> None:
    output = tmp_path / "reviews.csv"
    with pytest.raises(AdminError, match="16 MiB"):
        write_records(iter([{**ROWS[0], "text": text}]), SCHEMA, output)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("record", [{"missing": None}, {"text": "x", "count": -1, "flag": False}])
def test_schema_drift_fails_before_publication(tmp_path: Path, record: dict[str, object]) -> None:
    with pytest.raises(AdminError, match="declared"):
        write_records(iter([record]), SCHEMA, tmp_path / "reviews.parquet")
    assert list(tmp_path.iterdir()) == []


def test_parquet_batches_are_bounded_by_rows_and_bytes(tmp_path: Path) -> None:
    output = tmp_path / "reviews.parquet"
    records = ({**ROWS[0], "text": str(index)} for index in range(MAX_BATCH_ROWS + 1))
    write_records(records, SCHEMA, output)
    metadata = pq.read_metadata(output)
    assert [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)] == [1000, 1]

    write_records(
        iter([ROWS[0], {**ROWS[0], "text": "x" * (MAX_BATCH_BYTES + 1)}, ROWS[0]]), SCHEMA, output
    )
    metadata = pq.read_metadata(output)
    assert [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)] == [1, 1, 1]


def test_parquet_footer_does_not_retain_bulky_column_statistics(tmp_path: Path) -> None:
    output = tmp_path / "reviews.parquet"
    schema = pl.Schema(
        {"image_id": pl.String, "pipeline_metadata": pl.String, "comment": pl.String}
    )
    write_records(
        iter([{"image_id": "synthetic", "pipeline_metadata": "{}", "comment": ""}]), schema, output
    )
    metadata = pq.read_metadata(output).row_group(0)
    assert metadata.column(0).statistics is not None
    assert metadata.column(1).statistics is None
    assert metadata.column(2).statistics is None


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_publication_failure_preserves_previous_file(
    tmp_path: Path, suffix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / f"reviews.{suffix}"
    write_records(iter(ROWS), SCHEMA, output)
    previous = output.read_bytes()

    def fail_replace(*_args: object) -> None:
        raise OSError("Synthetic publication failure")

    monkeypatch.setattr("tools.tabular_output.os.replace", fail_replace)
    with pytest.raises(OSError, match="publication failure"):
        write_records(iter(ROWS), SCHEMA, output)
    assert output.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [output]
