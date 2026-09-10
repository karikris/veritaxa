from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import polars as pl
import pytest

from tools.candidate_input import iter_candidate_rows
from tools.candidate_rows import candidate_from_row
from tools.common import AdminError
from tools.import_candidates import import_file, main, read_candidate_frame
from tools.import_publish import import_spec


def spec():
    return import_spec(
        campaign_code="SYNTH-INPUT",
        internal_name="Synthetic",
        reviewer_name="Synthetic",
        batch_prefix="SYNTH-INPUT",
        target_scientific_name="Papilio exemplaris",
    )


def source_rows(count: int):
    return [
        {
            "image_id": f"synthetic-{i}",
            "image_url": f"https://images.example.invalid/{i}.jpg",
            "source_provider": "synthetic",
            "source_record_id": None if i % 2 else "",
            "pipeline_metadata": json.dumps({"nested": [None, True, "🦋"], "score": 0.25}),
            "extra_float": float(i),
            "extra_bool": bool(i % 2),
            "extra_text": 'A,"🦋"\nB' if i % 2 else "",
            "source_labels": "null" if i % 2 else '{"a":true}',
            "extra_nan": float("nan") if i % 2 else 0.5,
        }
        for i in range(count)
    ]


@pytest.mark.parametrize("suffix", ["csv", "parquet", "ndjson", "jsonl"])
def test_candidate_semantics_equal_legacy_reader_across_chunk_boundaries(
    tmp_path: Path, suffix: str
):
    path = tmp_path / f"input.{suffix}"
    frame = pl.DataFrame(source_rows(151))
    getattr(frame, f"write_{'ndjson' if suffix == 'jsonl' else suffix}")(path)
    expected = [candidate_from_row(row) for row in read_candidate_frame(path).iter_rows(named=True)]
    with closing(iter_candidate_rows(path)) as rows:
        assert [candidate_from_row(row) for row in rows] == expected
    assert import_file(path, spec()) == (1, 1, 151)


def test_json_preserves_sparse_struct_semantics_and_late_unknown_fields(tmp_path: Path):
    path = tmp_path / "input.ndjson"
    rows = source_rows(105)
    for index, row in enumerate(rows):
        row.pop("extra_nan")
        row["pipeline_metadata"] = {"even": index} if index % 2 == 0 else {"odd": index}
        row["initially_null"] = None
    rows[-1]["extra_late"] = ["🦋", 2, True]
    rows[-1]["pipeline_metadata"]["nested_late"] = {"retained": True}
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    original = read_candidate_frame(path).to_dicts()
    result = list(iter_candidate_rows(path))
    assert result[:-1] == original[:-1]
    assert result[-1]["extra_late"] == ["🦋", 2, True]
    assert result[-1]["pipeline_metadata"] == {
        "even": 104,
        "odd": None,
        "nested_late": {"retained": True},
    }
    assert result[-1]["initially_null"] is None


@pytest.mark.parametrize("suffix", ["csv", "parquet", "ndjson"])
def test_late_validation_never_resolves_database_configuration(tmp_path: Path, suffix: str):
    path = tmp_path / f"input.{suffix}"
    rows = source_rows(150)
    rows[-1]["image_url"] = "invalid synthetic URL"
    getattr(pl.DataFrame(rows), f"write_{suffix}")(path)
    database = Mock(side_effect=AssertionError("Must finish validation before touching database"))
    with pytest.raises(AdminError):
        import_file(path, spec(), database=database)
    database.assert_not_called()


def test_csv_retries_large_record_without_duplicating_preceding_rows(tmp_path: Path):
    path = tmp_path / "large.csv"
    rows = source_rows(120)
    for row in rows:
        row.pop("extra_nan")
    rows[-1]["pipeline_metadata"] = json.dumps({"payload": "x" * (8 * 1024 * 1024)})
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), quoting=csv.QUOTE_NOTNULL)
        writer.writeheader()
        writer.writerows(rows)
    result = list(iter_candidate_rows(path))
    assert len(result) == len(rows)
    assert [row["image_id"] for row in result] == [row["image_id"] for row in rows]
    assert len(json.loads(result[-1]["pipeline_metadata"])["payload"]) == 8 * 1024 * 1024


def test_source_mutation_is_detected_before_publication(tmp_path: Path):
    path = tmp_path / "input.ndjson"
    pl.DataFrame(source_rows(151)).write_ndjson(path)
    with closing(iter_candidate_rows(path)) as rows:
        next(rows)
        with path.open("ab") as output:
            output.write(b"\n")
        with pytest.raises(AdminError, match="changed during validation"):
            list(rows)


@pytest.mark.parametrize("suffix", ["parquet", "ndjson"])
@pytest.mark.parametrize("size_mib", [8, 17])
def test_full_file_path_handles_large_and_rejects_oversized_normalized_rows(
    tmp_path, suffix, size_mib
):
    path = tmp_path / f"large.{suffix}"
    rows = source_rows(105)
    rows[-1]["pipeline_metadata"] = json.dumps({"payload": "x" * (size_mib * 1024 * 1024)})
    getattr(pl.DataFrame(rows), f"write_{suffix}")(path)
    database = Mock(side_effect=AssertionError("Must not publish an oversized candidate"))
    if size_mib > 16:
        with pytest.raises(AdminError, match="16 MiB"):
            import_file(path, spec(), database=database)
        database.assert_not_called()
    else:
        assert import_file(path, spec()) == (1, 1, 105)


def test_parquet_retains_nested_dates_binary_and_decimal_metadata(tmp_path: Path):
    from datetime import UTC, date, datetime
    from decimal import Decimal

    row = source_rows(1)[0]
    row.update(
        extra_date=date(2026, 9, 10),
        extra_timestamp=datetime(2026, 9, 10, tzinfo=UTC),
        extra_binary=b"\x00\xff",
        extra_decimal=Decimal("1.2300"),
        extra_struct={"name": "🦋", "values": [1, None, 3]},
    )
    path = tmp_path / "nested.parquet"
    pl.DataFrame([row]).write_parquet(path)
    expected = [candidate_from_row(row) for row in read_candidate_frame(path).iter_rows(named=True)]
    assert [candidate_from_row(row) for row in iter_candidate_rows(path)] == expected


def test_dry_run_never_resolves_credentials_and_spool_errors_are_sanitized(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "input.parquet"
    pl.DataFrame(source_rows(1)).write_parquet(path)
    arguments = [
        "--input",
        str(path),
        "--campaign-code",
        "SYNTH-CLI",
        "--internal-name",
        "Synthetic",
        "--reviewer-name",
        "Synthetic",
        "--batch-prefix",
        "SYNTH-CLI",
        "--target-scientific-name",
        "Papilio exemplaris",
        "--dry-run",
    ]
    database = Mock(side_effect=AssertionError("Dry run cannot resolve credentials"))
    monkeypatch.setattr("tools.import_candidates.database_url", database)
    assert main(arguments) == 0
    database.assert_not_called()
    capsys.readouterr()
    monkeypatch.setattr(
        "tools.candidate_spool.sqlite3.connect",
        Mock(side_effect=sqlite3.OperationalError("synthetic-private-marker")),
    )
    assert main(arguments) == 1
    assert (
        capsys.readouterr().out
        == "Import failed. No candidate details or credentials were printed.\n"
    )
