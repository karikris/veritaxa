"""Bounded candidate readers with legacy tabular types and no silent field projection."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.csv as arrow_csv
import pyarrow.parquet as parquet

from tools.candidate_rows import REQUIRED_COLUMNS
from tools.common import AdminError

READ_ROWS = 64
TEXT_BATCH_BYTES = 1024 * 1024
MAX_TEXT_RECORD_BYTES = 64 * 1024 * 1024


def iter_candidate_rows(path: Path) -> Iterator[dict[str, object]]:
    """The caller must close the iterator on early failure (for example with closing())."""
    before = path.stat()
    try:
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            with parquet.ParquetFile(path, pre_buffer=False, buffer_size=65536) as source:
                _check_columns(source.schema_arrow.names)
                for batch in source.iter_batches(batch_size=READ_ROWS, use_threads=False):
                    yield from _arrow_rows(batch)
        elif suffix == ".csv":
            # Preserve the original 100-row Polars type inference, including unknown columns.
            schema = pl.scan_csv(path, glob=False).collect_schema()
            _check_columns(schema.names())
            yield from _csv_rows(path, pl.DataFrame(schema=schema).to_arrow().schema)
        elif suffix in {".ndjson", ".jsonl"}:
            schema = pl.scan_ndjson(path).collect_schema()
            _check_columns(schema.names())
            with path.open("rb") as source:
                pending: list[bytes] = []
                pending_bytes = 0
                while line := source.readline(MAX_TEXT_RECORD_BYTES + 1):
                    if len(line) > MAX_TEXT_RECORD_BYTES:
                        raise AdminError("Input JSON record exceeds the 64 MiB encoded limit.")
                    if not line.strip():
                        continue
                    if pending and (
                        len(pending) == READ_ROWS or pending_bytes + len(line) > TEXT_BATCH_BYTES
                    ):
                        yield from _json_rows(pending, schema)
                        pending.clear()
                        pending_bytes = 0
                    pending.append(line)
                    pending_bytes += len(line)
                if pending:
                    yield from _json_rows(pending, schema)
        else:
            raise AdminError("Input must use .parquet, .csv, .ndjson, or .jsonl.")
    except (pa.ArrowException, pl.exceptions.PolarsError, ValueError) as error:
        raise AdminError(
            "Candidate input could not be decoded without losing its declared types."
        ) from error
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise AdminError("Candidate input changed during validation; no campaign was published.")


def _check_columns(columns: list[str]) -> None:
    missing = REQUIRED_COLUMNS - set(columns)
    if missing:
        raise AdminError(f"Input is missing required columns: {', '.join(sorted(missing))}.")
    if len(columns) != len(set(columns)):
        raise AdminError("Duplicate input column names are not supported.")


def _arrow_rows(batch: pa.RecordBatch) -> Iterator[dict[str, object]]:
    # Polars' Arrow adapter preserves existing nested/map/date conversion semantics.
    # Slices share decoder buffers; only a small row view is converted at a time.
    for offset in range(0, batch.num_rows, READ_ROWS):
        frame = pl.from_arrow(batch.slice(offset, READ_ROWS))
        yield from frame.iter_rows(named=True, buffer_size=1)


def _csv_rows(path: Path, schema: pa.Schema) -> Iterator[dict[str, object]]:
    block_size = TEXT_BATCH_BYTES
    emitted = 0
    while True:
        skipped = 0
        try:
            with closing(
                arrow_csv.open_csv(
                    path,
                    read_options=arrow_csv.ReadOptions(block_size=block_size, use_threads=False),
                    parse_options=arrow_csv.ParseOptions(newlines_in_values=True),
                    convert_options=arrow_csv.ConvertOptions(
                        column_types=schema,
                        null_values=[""],
                        strings_can_be_null=True,
                        quoted_strings_can_be_null=False,
                        true_values=["true", "True", "TRUE"],
                        false_values=["false", "False", "FALSE"],
                    ),
                )
            ) as reader:
                _check_columns(reader.schema.names)
                for batch in reader:
                    if skipped + batch.num_rows <= emitted:
                        skipped += batch.num_rows
                        continue
                    start = max(0, emitted - skipped)
                    skipped += batch.num_rows
                    for row in _arrow_rows(batch.slice(start)):
                        emitted += 1
                        yield row
            return
        except pa.ArrowInvalid as error:
            if "straddl" not in str(error).lower() or block_size >= MAX_TEXT_RECORD_BYTES:
                raise
            # Arrow requires a complete large CSV record to span at most two blocks.
            # Retry the same declared schema with a larger decoder buffer; never repeat
            # already-emitted rows. The outer file fingerprint detects source replacement.
            block_size *= 2


def _json_rows(lines: list[bytes], schema: pl.Schema) -> Iterator[dict[str, object]]:
    frame = pl.read_ndjson(b"".join(lines), schema=schema, low_memory=True, batch_size=READ_ROWS)
    if frame.height != len(lines):
        raise AdminError("Input JSON rows did not match the decoded record count.")
    for row, line in zip(frame.iter_rows(named=True, buffer_size=1), lines, strict=True):
        original = json.loads(line)
        if not isinstance(original, dict):
            raise AdminError("Each input JSON record must be an object.")
        # The legacy inference shapes known fields (for example sparse structs and
        # numeric promotion). Preserve fields appearing after inference instead of
        # silently projecting them away, including nested metadata keys.
        yield _restore_unknown(row, original)


def _restore_unknown(converted: object, original: object) -> object:
    if converted is None and original is not None:
        return original
    if isinstance(converted, dict) and isinstance(original, dict):
        for key, value in original.items():
            converted[key] = _restore_unknown(converted[key], value) if key in converted else value
    elif isinstance(converted, list) and isinstance(original, list):
        for index, value in enumerate(original):
            converted[index] = _restore_unknown(converted[index], value)
    return converted
