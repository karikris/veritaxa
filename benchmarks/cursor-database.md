# Cursor selection and complete RPC timing

This benchmark uses real application migrations, two synthetic reviewers and
20 KiB synthetic metadata per item. It never connects to the linked project.
`VERITAXA_CURSOR_DSN` must explicitly target a loopback PostgreSQL server (or the
documented private test socket) and database `veritaxa_cursor_synthetic`. The
benchmark refuses any other database. Run it only on a disposable local cluster.

## Reproduction

Create an empty `veritaxa_cursor_synthetic` database in a disposable PostgreSQL
cluster with pgTAP installed. Use its owner/superuser connection: fixture creation
requires test roles, then application migrations establish real restricted grants.
For standalone PostgreSQL, load `benchmarks/cursor_fixture.sql` first, then the
repository migrations in filename order. Use `psql -X --set=ON_ERROR_STOP=1` for
these multi-statement files. The fixture refuses an existing Auth/application
schema and never overrides existing roles. It is a minimal Auth table/claim-function
fixture, **not** an Auth server or an authentication-flow test.

For the before/after comparison, initially apply migrations only through
`20260801073118_add_review_cursor_and_editable_reviews.sql`, then run:

```sh
uv run python -m benchmarks.cursor_database case --output /tmp/veritaxa-cursor-before.json
```

Apply `20260910151534_seek_review_cursor_positions.sql` to that disposable
database and run:

```sh
uv run python -m benchmarks.cursor_database seek --output /tmp/veritaxa-cursor-after.json
```

Do not restore an old function on a live project to obtain a baseline. Each
output must not already exist; reports identify the installed function by hash
and reject a selection style that disagrees with it. Three repetitions at each
of 1,000, 10,000 and 100,000 items are the default. Each direction/wrap/resume case
has 10 warm-ups and 30 recorded calls. `--samples` and `--repeats` allow explicit
overrides. Fixtures are rolled back after every size; vacuum/analyze clears old
synthetic row versions before the next run. No campaigns or reviews are published.
The 1,000-item size is the current importer batch cap; larger sizes are stress tests.

## What the numbers mean

Selection-only timings run as the owner and include the local driver round trip.
The wrap path includes both range lookup and fallback lookup when required.
`EXPLAIN (ANALYZE, BUFFERS)` separately records each selection statement, including
the wrap fallback even for ordinary navigation. Seek plans must use batch/position
index conditions and `LIMIT 1`, without a sort, sequential scan or filtered prefix.
Both existing batch/position B-trees are eligible; no speculative index is added.
Positions are unique within a batch, so an ID tie-breaker is unnecessary. Including
it caused an incremental sort on empty boundary ranges in the initial experiment.

Full RPC timings run as `authenticated`, with a real active private profile and
the corresponding claim. They include authorization, exact own-review progress
counts, current answer/version and response assembly. Every timed call checks
the expected item and progress; all items also have a second review to detect
cross-reviewer counting errors. Timings exclude the HTTP gateway, network latency
to a hosted service and Auth service operations. They are **not** page-load timings.

Exact progress counting remains proportional to batch size. Resume keeps its
existing first-own-unreviewed/otherwise-first selection and is measured separately;
it has no new selection-only path. No counters, cache, RLS relaxation or historical
RPC removal is included. Run `supabase/tests/review_cursor.test.sql` and
`supabase/tests/review_security.test.sql` for edge cases and the complete security
contract; CI runs those against the local Supabase service, not this Auth fixture.

The [September measurements](results/cursor-2026-09-11.json) retain individual
timings, summarized plans and three-run p50/p95 medians/ranges. Full JSON plans
and per-call timing samples are emitted by the commands above.
