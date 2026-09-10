"""Private, incremental staging and atomic publication of flat admin exports."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from tools.common import AdminError

MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_BATCH_ROWS = 1000
MAX_BATCH_BYTES = 4 * 1024 * 1024


def validate_output_path(output: Path) -> None:
    if output.suffix.lower() not in {".csv", ".parquet"}:
        raise AdminError("Output must use .parquet or .csv.")


def write_records(records: Iterable[dict[str, object]], schema: pl.Schema, output: Path) -> int:
    """Preserve nulls/types/order and replace only on complete success.

    CSV retains one row. Parquet retains a batch of at most 1,000 rows or 4 MiB,
    plus its Arrow encoding. A row above the batch budget is written alone; a
    row above 16 MiB is rejected, without publishing partial data. No data spool
    or whole-result frame is required.
    """
    validate_output_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".veritaxa-export-", dir=output.parent) as temporary:
        stage = Path(temporary)
        result = stage / output.name
        count = 0
        if output.suffix.lower() == ".csv":
            with result.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, quoting=csv.QUOTE_NOTNULL, lineterminator="\n")
                writer.writerow(schema.names())
                for record in records:
                    _check_record(record, schema)
                    writer.writerow(
                        str(value).lower() if isinstance(value, bool) else value
                        for value in (record[column] for column in schema)
                    )
                    count += 1
        else:
            count = _write_parquet(records, schema, result)
        result.chmod(0o600)
        with result.open("rb") as completed:
            os.fsync(completed.fileno())
        os.replace(result, output)
    return count


def _write_parquet(records: Iterable[dict[str, object]], schema: pl.Schema, result: Path) -> int:
    # CSV-only jobs do not load the Arrow runtime.
    import pyarrow as pa
    import pyarrow.parquet as pq

    types = {
        pl.String: pa.string(),
        pl.Boolean: pa.bool_(),
        pl.UInt32: pa.uint32(),
        pl.Null: pa.null(),
    }
    arrow_schema = pa.schema([(column, types[dtype]) for column, dtype in schema.items()])
    count = 0
    pending: list[dict[str, object]] = []
    pending_bytes = 0
    # Min/max statistics on bulky JSON/comment fields are not useful for filtering
    # and would retain large values in every row-group footer until the file closes.
    statistics = [
        column
        for column in schema
        if column not in {"source_labels", "pipeline_metadata", "comment"}
    ]
    with pq.ParquetWriter(
        result, arrow_schema, compression="zstd", use_dictionary=False, write_statistics=statistics
    ) as writer:
        for record in records:
            byte_count = _check_record(record, schema)
            if pending and (
                len(pending) == MAX_BATCH_ROWS or pending_bytes + byte_count > MAX_BATCH_BYTES
            ):
                writer.write_batch(pa.RecordBatch.from_pylist(pending, schema=arrow_schema))
                pending.clear()
                pending_bytes = 0
            pending.append(record.copy())
            pending_bytes += byte_count
            count += 1
        if pending:
            writer.write_batch(pa.RecordBatch.from_pylist(pending, schema=arrow_schema))
    return count


def _check_record(record: dict[str, object], schema: pl.Schema) -> int:
    if record.keys() != schema.keys():
        raise AdminError("Export row does not match its declared columns.")
    byte_count = 0
    for column, dtype in schema.items():
        value = record[column]
        if value is None:
            continue
        if dtype == pl.String and isinstance(value, str):
            if len(value) > MAX_RECORD_BYTES:
                raise AdminError("Export row exceeds the 16 MiB limit.")
            byte_count += len(value.encode("utf-8"))
        elif dtype == pl.Boolean and isinstance(value, bool):
            byte_count += 1
        elif dtype == pl.UInt32 and type(value) is int and 0 <= value <= 0xFFFFFFFF:
            byte_count += 4
        else:
            raise AdminError("Export row does not match its declared types.")
        if byte_count > MAX_RECORD_BYTES:
            raise AdminError("Export row exceeds the 16 MiB limit.")
    return byte_count
