from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import psycopg
import pytest

from tools.common import AdminError
from tools.export_reviews import (
    BULKY_COLUMNS,
    EXPECTED_RESULT_PRIORITY,
    EXPORT_COLUMNS,
    SCHEMA_VERSION,
    add_derived_mappings,
    derived_mappings,
    export_query,
    export_reviews,
    export_schema,
    iter_export_records,
    summarize_votes,
)


def test_lean_query_projects_metadata_out_before_decoding() -> None:
    for consensus in [False, True]:
        full, _ = export_query(consensus=consensus)
        lean, columns = export_query(consensus=consensus, lean=True)
        for column in BULKY_COLUMNS:
            assert f"item.{column}" in full
            assert f"item.{column}" not in lean
            assert column not in columns
        assert "%s" in lean
        assert "campaign.campaign_code = %s" in lean
    raw, columns = export_query()
    assert columns == EXPORT_COLUMNS
    assert raw.endswith("order by batch.position, item.position, review.created_at, review.id")


@pytest.mark.parametrize("label", EXPECTED_RESULT_PRIORITY)
def test_incremental_derived_flags_match_existing_frame_mapping(label: str) -> None:
    row = {"human_label": label}
    assert derived_mappings(row) == {
        key: value
        for key, value in add_derived_mappings(pl.DataFrame([row])).row(0, named=True).items()
        if key != "human_label"
    }


def test_ties_are_excluded_from_training_even_when_priority_selects_a_positive() -> None:
    summary = summarize_votes({"adult_butterfly": 1, "plant": 1})
    assert summary == {
        "human_label": "adult_butterfly",
        "review_count": 2,
        "reviews_unanimous": False,
        "consensus_tied": True,
    }
    assert derived_mappings(summary)["excluded_from_automatic_training"] is True
    assert add_derived_mappings(pl.DataFrame([summary]))[
        "excluded_from_automatic_training"
    ].to_list() == [True]


@pytest.mark.parametrize("counts", [{}, {"plant": 0}, {"plant": -1}, {"plant": True}])
def test_invalid_vote_counts_are_rejected(counts: dict[str, int]) -> None:
    with pytest.raises(AdminError, match="counts"):
        summarize_votes(counts)


def test_cancelled_read_closes_stream_cursor_and_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    row = [None] * len(EXPORT_COLUMNS)
    row[EXPORT_COLUMNS.index("pipeline_metadata")] = {"z": [True, None, "🦋"], "a": 1}
    row[EXPORT_COLUMNS.index("reviewed_at")] = "2026-09-10T00:00:00Z"

    def stream(*args: object, size: int):
        assert args == (export_query()[0], (SCHEMA_VERSION, "SYNTH"))
        assert size == 1
        try:
            yield row
            raise AssertionError("The reader must not eagerly consume all rows")
        finally:
            events.append("stream closed")

    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.stream.side_effect = stream
    monkeypatch.setattr("tools.export_reviews.psycopg.connect", lambda _dsn: connection)
    with closing(iter_export_records("synthetic", "SYNTH")) as records:
        first = next(records)
        assert first["pipeline_metadata"] == '{"a":1,"z":[true,null,"🦋"]}'
        assert (
            json.loads(str(first["pipeline_metadata"]))
            == row[EXPORT_COLUMNS.index("pipeline_metadata")]
        )
    assert events == ["stream closed"]
    assert connection.read_only is True
    assert connection.isolation_level == psycopg.IsolationLevel.REPEATABLE_READ
    connection.cursor.return_value.__exit__.assert_called_once()
    connection.__exit__.assert_called_once()


def test_invalid_output_does_not_connect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connect = MagicMock(side_effect=AssertionError("Must not connect"))
    monkeypatch.setattr("tools.export_reviews.psycopg.connect", connect)
    with pytest.raises(AdminError, match="Output"):
        export_reviews("synthetic", "SYNTH", tmp_path / "invalid.json")
    connect.assert_not_called()


def test_empty_schemas_are_explicit_for_all_projections() -> None:
    for consensus in [False, True]:
        for derived in [False, True]:
            full = export_schema(consensus=consensus, derived=derived)
            lean = export_schema(consensus=consensus, derived=derived, lean=True)
            assert lean.names() == [column for column in full if column not in BULKY_COLUMNS]
            assert all(lean[column] == full[column] for column in lean)
