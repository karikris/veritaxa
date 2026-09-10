# Synthetic memory checks

For the 1,000-navigation real-raster browser/decoded-memory gate, see
[browser-memory.md](browser-memory.md). The sections below cover the admin tools.

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

Repeat at 10,000 and 100,000 rows in fresh processes for baseline comparisons.
Generate fixtures separately so fixture creation does not inflate measured import
RSS. Fixture generation is now bounded. The original baseline implementation is
preserved at commit `fe3ad91`; current export/consensus probes intentionally call
the eager small-frame compatibility APIs, not the streaming CLI.

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

## Complete database-to-file export gate

Use a **new disposable local PostgreSQL database** named `veritaxa_synthetic`.
Never point this fixture at a Supabase application database. The minimal fixture
models the export columns, relationships and indexes; it does not model Auth,
RLS or RPC authorization, which remain covered by the separate Supabase suite.
The commands require an explicit loopback or private local Unix-socket DSN and
never load `.env.admin`. Initialization and seeding refuse existing fixture IDs;
they do not drop or replace data.

```sh
export VERITAXA_SYNTHETIC_DSN='host=127.0.0.1 dbname=veritaxa_synthetic'
uv run python -m benchmarks.export_database init
uv run python -m benchmarks.export_database seed 10000
uv run python -m benchmarks.export_database seed 100000
uv run pytest tools/tests/test_export_database.py
uv run python -m benchmarks.export_gate --report /tmp/veritaxa-export-memory.json
```

CI supplies its own disposable PostgreSQL 17 service and publishes only aggregate
benchmark metrics. The gate runs every full/lean, raw/consensus, CSV/Parquet path
at both sizes, three fresh Python processes per case. Each item carries a 20 KiB
payload plus nested JSON; one to three synthetic reviewers produce 22,500 raw
rows at 10,000 items and 225,000 at 100,000. Consensus produces one row per item.
Output count is checked so an empty/missing fixture cannot pass the memory gate.

The RSS limit is 256 MiB for **every run**, with at most 64 MiB growth between
size medians. Reports retain all measurements plus medians, ranges and runtime
versions. RSS covers the driver, JSON decoder, reducer and completed file writer,
but not the PostgreSQL server. No thread-pool override is required. The gate uses
Linux `ru_maxrss` units. Outputs are deleted after each measurement; allow at least
5 GiB of temporary disk space for the largest full CSV file.

Integration tests separately cover output types/nulls/order/canonical JSON,
multiple reviewers, concurrent edits, stream cancellation, slow/failing writes,
an accepted 8 MiB metadata payload and a rejected 17 MiB payload. Oversized cases
are correctness tests, not evidence for the 20 KiB-fixture RSS bound. The output
limit is checked after the driver decodes a row. Review the documented policy
before exporting exceptionally large single records.

## Import spool development probe

```sh
uv run python -m benchmarks.import_spool 10000 --shuffle-seed 0
uv run python -m benchmarks.import_spool 100000 --shuffle-seed 0
```

This synthetic-only probe validates, orders and consumes a private SQLite spool;
it does not read a candidate file or insert into Postgres. It is **not** the final
import gate; use the complete gate below to measure the CLI's full processing path.
Each invocation starts a fresh child so a shell launcher cannot contribute an
inherited `ru_maxrss` high-water mark. It also reports initial and post-validation
RSS. As with the export gate, use Linux and compare repeated ranges and medians.

`sha256-v1` shuffle orders every input ordinal globally by the SHA-256 digest of
the ASCII string `veritaxa-shuffle-sha256-v1:<seed>:<zero-based ordinal>`, breaking
hash ties by ordinal. The ordering is independent of insertion chunk size and
treats seed 0 normally; it does **not** reproduce legacy Polars PRNG order. No
metadata or full permutation is retained in a Python list. Changing byte-sized
insertion chunks never changes the requested logical batch size or item positions.

## Complete importer gate

Create a new disposable local database named `veritaxa_import_synthetic` (separate
from the export fixture database). Initialization extracts the actual campaign,
batch and item DDL and applicable constraints from the retained migrations. It
does not pretend to implement Supabase Auth/RLS; the separate security job covers
those. Never use an application database or `.env.admin` for this harness.

```sh
export VERITAXA_IMPORT_DSN='host=127.0.0.1 dbname=veritaxa_import_synthetic'
export VERITAXA_IMPORT_FIXTURES=$(mktemp -d)
uv run python -m benchmarks.import_database init
for size in 10000 100000; do
  for format in csv parquet ndjson; do
    uv run python -m benchmarks.import_database generate "$size" --format "$format"
  done
done
uv run pytest tools/tests/test_import_database.py tools/tests/test_candidate_input.py
uv run python -m benchmarks.import_gate --report /tmp/veritaxa-import-memory.json
```

Fixture generation runs separately and refuses to replace existing files. The
gate includes source decoding, normalization, disk staging, global shuffle when
selected, JSON adaptation, inserts and the final commit. It tests all three
formats at 10,000 and 100,000 rows, unshuffled and seed 0, in three fresh processes
per case. JSONL shares the NDJSON reader and is covered by equivalence tests.
Six additional Parquet runs compare pipeline inserts and COPY using identical
row mapping and transaction semantics. Every run must stay below 256 MiB RSS;
median growth between sizes must stay below 64 MiB. Server memory is excluded.

Each run uses a unique synthetic campaign, verifies committed item counts,
metadata payload lengths and ordinal checksum, then removes only its own records.
Failures during publication roll back; the integration suite also checks a real
late uniqueness violation and verifies uncommitted batches are invisible to a
second connection. Dry-run follows the same validation path without opening any
database. Reports contain only aggregate metrics, not candidate rows or credentials.

The CLI retains pipelined inserts and offers no insertion-method switch. COPY's
end-to-end benefit is measured against the complete path, not assumed from a
microbenchmark. PostgreSQL also [restricts COPY FROM with row-level security](https://www.postgresql.org/docs/current/sql-copy.html);
the comparison runs as the owner of disposable synthetic tables, never by relaxing
application policies.
