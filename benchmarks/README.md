# Synthetic memory baseline

Run from the repository root using the project Python environment. No credentials,
database connection, real images or private campaigns are used. Do not commit
generated fixture files or output captures containing non-synthetic data.

```sh
audit_fixtures=$(mktemp -d)
export VERITAXA_AUDIT_FIXTURES="$audit_fixtures"
uv run python -m benchmarks.admin_memory generate 1000
uv run python -m benchmarks.admin_memory import 1000
uv run python -m benchmarks.admin_memory export 1000
uv run python -m benchmarks.admin_memory consensus 1000
```

Repeat at 10,000 and 100,000 rows in fresh processes for the implementation gates.
Generate fixtures separately so fixture creation does not inflate measured import
RSS. The initial eager baseline generator itself is not memory-bounded; replace
its fixture preparation before running large CI cases.

The baseline measures import read/plan construction and export conversion using
a mocked decoded-row cursor. It excludes SQL/network/libpq buffers, import
insertion and final export writing. Consensus initially uses one vote per item.
The `bounded-validator-probe` checks count and identifier order only: it is not a
complete streaming importer and does not preserve cross-chunk batch numbering.
Final gates must exercise real end-to-end paths, multiple votes, nested metadata,
oversized rows and failure handling; these baseline probes are not substitutes.

## Bounded writer probe

```sh
uv run python -m benchmarks.writer_memory 10000
uv run python -m benchmarks.writer_memory 100000
uv run python -m benchmarks.writer_memory 100000 --format csv
```

Each invocation generates synthetic rows lazily, writes a complete file in a
private temporary directory and removes it on exit. It requires no database or
credentials. Run each size at least three times in fresh processes; compare RSS
ranges and medians, not just an individual peak. Runtime: Python 3.14.5, Polars
1.43.0 (18 threads), PyArrow 25.0.1, Linux for the initial September measurements.
This measures the writer only, not the entire export or import pipeline.
