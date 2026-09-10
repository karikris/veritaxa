from __future__ import annotations

from itertools import product

import pytest

from benchmarks.export_database import synthetic_dsn
from benchmarks.export_gate import SIZES, summarize
from tools.common import AdminError


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "host=example.invalid dbname=veritaxa_synthetic",
        "host=127.0.0.1 dbname=postgres",
        "host=127.0.0.1 dbname=veritaxa_synthetic hostaddr=192.0.2.1",
        "host=/tmp/veritaxa-postgres-test,example.invalid dbname=veritaxa_synthetic",
        "host=127.0.0.1 dbname=veritaxa_synthetic service=synthetic",
    ],
)
def test_benchmark_refuses_nonlocal_or_implicit_database(monkeypatch, dsn) -> None:
    monkeypatch.setenv("VERITAXA_SYNTHETIC_DSN", dsn)
    with pytest.raises(AdminError, match="disposable local"):
        synthetic_dsn()


@pytest.mark.parametrize(
    "variable,value", [("PGHOSTADDR", "192.0.2.1"), ("PGSERVICE", "synthetic")]
)
def test_benchmark_refuses_implicit_libpq_connection_redirection(monkeypatch, variable, value):
    monkeypatch.setenv("VERITAXA_SYNTHETIC_DSN", "host=127.0.0.1 dbname=veritaxa_synthetic")
    monkeypatch.setenv(variable, value)
    with pytest.raises(AdminError, match="disposable local"):
        synthetic_dsn()


def test_memory_gate_checks_each_peak_and_median_growth() -> None:
    runs = [
        {
            "consensus": consensus,
            "lean": lean,
            "format": file_format,
            "items": size,
            "peak_rss_mib": 100.0,
            "seconds": 1.0,
        }
        for _repeat, consensus, lean, file_format, size in product(
            range(3), (False, True), (False, True), ("csv", "parquet"), SIZES
        )
    ]
    assert all(summary["passed"] for summary in summarize(runs))
    runs[0]["peak_rss_mib"] = 257.0
    summary = summarize(runs)[0]
    assert summary["sizes"][0]["rss_median_mib"] == 100.0
    assert summary["passed"] is False  # A single over-budget peak cannot hide in a median.
    for run in runs:
        run["peak_rss_mib"] = 165.0 if run["items"] == SIZES[1] else 100.0
    assert all(not summary["passed"] for summary in summarize(runs))
