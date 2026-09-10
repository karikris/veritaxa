# September efficiency implementation

User direction: backlog ButterflyLens, implement the VeriTaxa review plan,
commit each focused change and push after each verified phase. Only VeriTaxa
application code is in scope. Existing ButterflyLens edits remain untouched.

Baseline: `50b69126d4a52edbfbbbae57704b78ede2b35dbb`. Local main was clean and
fast-forwarded from `a390030` before implementation. The full private audit and
reproduction artifacts remain outside this public-code repository.

## Phases and evidence

| Phase | Required result                                                                                             | Status                      |
| ----- | ----------------------------------------------------------------------------------------------------------- | --------------------------- |
| 0     | Current baseline, synthetic profiling harness, preservation contracts                                       | Verified and pushed         |
| 1     | Session/image ownership, versioned drafts, immutable retry payloads, typed conflicts, Unicode parity        | Verified and pushed         |
| 2     | Bounded export/consensus, full and explicit lean projection, atomic output                                  | Verified and pushed         |
| 3     | Bounded import/validated spool, metadata preservation, deterministic shuffle, atomic publish                | Local gates passed; CI next |
| 4     | Stable DOM, bounded drafts, explicit display/full-resolution policy, browser soak                           | Pending                     |
| 5     | Forward cursor-seek migration, pgTAP edge cases, measured local plans                                       | Pending                     |
| 6     | Dead-code removal, consolidated capabilities/normalization, Python/schema parity, safe compatibility cutoff | Pending                     |

No phase is complete merely because its unit tests pass. Record commit IDs,
pushes, CI/deployment runs and measured gates in the work log. Applied migration
history and private records must remain intact. Legacy RPC retirement requires
consumer/cutoff evidence; do not silently remove compatibility still in use.

## Acceptance gates

- Admin RSS: at most 256 MiB on 10,000 and 100,000 synthetic rows carrying
  20 KiB metadata, with at most 64 MiB growth between sizes. Test nested metadata
  and oversized rows separately; include driver/decoder/writer buffers.
- Application buffers: at most 1,000 rows or 16 MiB metadata per batch, at most
  two retained batches; an explicit policy for an oversized single row.
- Browser: one current item/image attempt; preserve nodes on label/comment/status
  updates; at most 256 drafts and 1 MiB serialized drafts, without silent loss.
  Run a 1,000-navigation soak and inspect JS and decoded-image/process memory.
- Images: prefer valid upstream renditions at most 1,600 pixels on the longest
  edge; original inspection is explicit, no application-owned image mirror.
- SQL: indexed range selection including wrap-around, resume, empty, complete
  and multi-reviewer cases. Measure full RPC timing separately from selection.
- Bundle: at most 70 KiB gzip, or an explicitly justified measured change.
- Verification: frontend/Python unit tests, lint/format/type checks, synthetic
  browser tests, local database security tests, private-data scan, clean diff.

## Preservation contracts

### Import

Unshuffled imports preserve row order, source identity, all retained metadata,
batch ordering and per-item positions. Unknown columns currently enter pipeline
metadata: projection cannot silently discard them. Preserve documented handling
of nulls, Unicode, JSON normalization and collisions. Correct seed 0 deliberately;
global shuffle must stay global and its reproducibility algorithm be explicit.

Dry-run never connects to a database. Late validation or insertion failure must
not publish a partial campaign. Private temporary spools and diagnostic errors
must not expose task data. Benchmark pipelined inserts versus COPY before changing
the insertion mechanism.

### Export

The default full projection retains the existing columns, types, null semantics
and source provenance. Raw rows order by batch position, item position, review
creation and review ID. Consensus orders by campaign code, batch code and image
ID. Keep these distinct contracts. JSON semantic equality is required; existing
canonical JSON serialization must not drift accidentally or become double encoded.

Reduce votes without retaining repeated metadata. Preserve dates, review counts,
unanimity and tie flags. Exclude tied decisions from automatic training explicitly.
Use a consistent read snapshot and publish an output only after it is complete;
a failed export must not overwrite a previous completed file. Preserve the
single-file CSV/Parquet CLI contract. Lean output is opt-in, never a silent loss
of full-export provenance.

### Browser and database

Only the authenticated owner may update their current review, using the draft's
base version. Late callbacks must not cross session, image or lifecycle ownership.
Ambiguous writes retain an immutable retry request: cancelling a browser wait
does not establish database rollback. Conflict comparison/reapply is explicit.

Keep metadata/credentials out of browser state and logs, preserve restricted RPC
responses, safe search paths, grants and RLS. The Supabase SDK, validation at trust
boundaries, historical schemas/migrations and reviewer data are not dead code.

## Work log

- Backlogged all ButterflyLens work in the external workspace backlog without
  changing its worktree. Started VeriTaxa from current remote main.
- Phase 0: recorded the preservation contracts and checked in the synthetic-only
  baseline harness. Baseline unit checks: 32 frontend and 22 Python tests; type,
  lint and production build checks pass (58.32 KiB gzip JavaScript). The baseline
  remote CI and database jobs passed at `50b6912`.
- Local browser dependencies need OS authentication for installation; Docker
  socket access is denied even outside the Codex sandbox. These are verification
  environment limits, not passing browser/database results. Remote CI covers
  both suites; later performance phases still require measured runtime evidence.
- Phase 0 commit `fe3ad91` pushed; [CI 34472952988](https://github.com/karikris/veritaxa/actions/runs/34472952988)
  passed application/browser and database security jobs.
- Phase 1 focused commits: `cf7803e` (callback ownership), `063859f` (Unicode
  round-trip and allocation-free counting), followed by versioned drafts and
  immutable retries. The draft now owns its label, comment, base version and
  pending request together. Typed version/submission conflicts require explicit
  comparison and reapply; choosing a saved answer does not write to the database.
- Phase 1 local evidence: 58 frontend unit tests and 14 desktop/mobile browser
  tests pass, including actual retry-after-edit and conflict/reapply browser
  flows. Temporary user-local Chromium libraries enabled local browser checks
  without changing system packages. They are outside the repository. No live
  review records or schema were changed. Client version is `veritaxa-web/0.3.0`.
- Phase 1 final local gates also passed: 22 Python tests, TypeScript, ESLint,
  Prettier, Ruff and whitespace checks. Production JavaScript is 59.46 KiB gzip;
  synthetic conflict/retry fixtures are absent from the built output.
- Phase 1 commit `d4e798f` and its two preceding focused commits pushed;
  [CI 34474319234](https://github.com/karikris/veritaxa/actions/runs/34474319234)
  and [Pages 34474539177](https://github.com/karikris/veritaxa/actions/runs/34474539177)
  both passed at the pushed commit.
- Phase 2 started with a bounded atomic writer (`163e981`), integrated into the
  existing exporter. Null/empty-string distinctions, schema, order, batch byte/row
  limits, oversized-row handling and late/publication failure tests passed.
  At that point the database reader and consensus were still eager; the later
  streaming commit below replaces those CLI paths.
- Added pinned PyArrow 25.0.1 for incremental Parquet writing after measuring the
  existing-stack NDJSON/Polars sink at 629 MiB for 10,000 rows (295 MiB even with
  one thread). This follows the plan's dependency decision gate. The Arrow writer
  uses at most 1,000 rows or 4 MiB per batch; a row up to 16 MiB is written alone,
  larger rows fail without replacing completed output. CSV does not import Arrow.
- Writer-only fresh-process probes (20 KiB synthetic metadata per row): CSV
  44.94 MiB at 10,000 rows and 44.93 MiB at 100,000; Parquet three-run medians
  133.67 and 133.96 MiB, ranges 133.53–133.67 and 133.81–134.09 MiB. These include
  output writing but exclude database/JSON decoding and consensus. Full pipeline
  gates, nested metadata and driver-backed runs remain required.
- Dependency follow-up for phase 6: the existing Polars 1.43.0 pin is now yanked
  on PyPI without a supplied reason. It was retained for baseline equivalence;
  assess a tested replacement or removal as the bounded pipelines supersede it.
- Phase 2 commits `e050bbb` and `0a14ed1`: omit bulky Parquet footer statistics;
  stream one libpq result row at a time; aggregate label counts in SQL before
  fetching item metadata once per consensus row. Full provenance remains the
  default, with explicit SQL-level `--lean` projection. Existing eager helpers
  are compatibility APIs only, not called by the CLI. Tied consensus is now
  explicitly excluded from automatic training when derived flags are requested.
- Phase 2 correctness evidence: 89 Python tests passed, including a disposable
  local PostgreSQL 18.3 driver-backed suite for all eight export combinations,
  exact columns/types/nulls/canonical JSON, distinct raw/consensus order,
  read-only repeatable-read transactions, concurrent edits, cancellation,
  slow/late writer failure, and 8 MiB accepted / 17 MiB rejected metadata. Timestamp
  assertions preserve the database's zone representation and compare instants.
  No live Supabase data or schema was changed. The row limit is post-decode;
  arbitrary single-row JSON decoder allocation is not covered by the RSS bound.
- Phase 2 complete export-memory gate passed all 48 fresh-process cases (three
  runs each at 10,000 and 100,000 items, full/lean, raw/consensus, CSV/Parquet).
  Raw output contains 22,500 and 225,000 reviews; metadata is 20 KiB plus nested
  JSON per item. Full raw CSV medians: 60.01 / 60.15 MiB; full raw Parquet:
  148.81 / 188.30 MiB (large-case range 187.72–189.11). Full consensus Parquet:
  147.27 / 154.70 MiB. Every run stayed below 256 MiB; largest median growth
  was 39.49 MiB, below 64 MiB. The driver/decoder/writer are included, server
  memory excluded. [Full aggregate measurements](../benchmarks/results/export-2026-09-10.json)
  retain versions, medians, ranges and individual runs. A separate CI job repeats
  this gate on disposable PostgreSQL 17 and publishes aggregate metrics only.
- Phase 2 pushed through `a3bd232`; [CI 34477826371](https://github.com/karikris/veritaxa/actions/runs/34477826371)
  passed the application, Supabase security and new driver-backed memory jobs.
  The downloaded CI artifact confirms all 48 cases passed on Python 3.12.3 and
  PostgreSQL 17.11, largest peak 206.22 MiB and largest median growth 38.65 MiB.
  Local final checks passed 58 frontend and 14 desktop/mobile browser tests,
  lint/type/format/data-leak checks and the 59.46 KiB gzip bundle gate.
  [Pages 34479299018](https://github.com/karikris/veritaxa/actions/runs/34479299018)
  also passed at the pushed phase commit.
- Phase 3 started by extracting shared normalization (`2ea1c07`) without changing
  legacy candidate semantics. The private SQLite spool validates metadata and
  final logical batches before exposing any candidates; 4 MiB insertion chunks
  keep batch/item positions independent of byte boundaries. It rejects normalized
  rows over 16 MiB and nonfinite JSON before database publication. Global
  `sha256-v1` shuffle is explicitly different from legacy Polars ordering, treats
  seed 0 as a seed, and has a fixed-order regression fixture. Normalized metadata,
  collisions, cross-batch membership, cancellation cleanup, finite-value checks,
  read-only staging and one accepted 8 MiB payload are tested.
- Phase 3 spool-only fresh-child measurements with global seed 0: three runs at
  10,000 rows used 33.86 MiB; 100,000-row range 34.84–35.01 MiB (median 34.87).
  These **exclude file readers and database insertion**. A direct-shell probe
  initially reported an inherited launcher high-water mark around 155 MiB before
  validation even began; the probe now forks explicitly and records its initial
  high-water mark. Export CI already uses fresh child processes. These were
  staging-only measurements; the complete importer results below supersede them.
- Phase 3 commits `56c54e1` and `2d89c46` integrate bounded CSV/Parquet/NDJSON
  readers with the validated spool and one atomic publication transaction. CLI
  dry-run never resolves credentials or connects. Known types retain legacy
  inference; late unknown NDJSON fields are preserved, including nested keys.
  Reader equivalence, large-record limits, changed-file detection, shuffle and
  byte-chunk positions are tested. Real PostgreSQL tests use the production
  table constraints, check all candidate fields and prove rollback after a late
  uniqueness violation, interrupted input or mismatched final count. A second
  connection cannot see the partially inserted campaign. No live data or schema
  was changed, and no RLS/grants were relaxed for tests.
- Phase 3 complete import gate passed all 42 fresh-process cases: three runs at
  both 10,000 and 100,000 rows, each with 20 KiB plus nested metadata. CSV,
  Parquet and NDJSON pipeline paths run both unshuffled and with seed 0; six
  additional Parquet runs compare COPY. Largest peak: 179.68 MiB; all median
  growth values were negative, passing the 256 MiB / 64 MiB gates. Unshuffled
  pipeline medians at the two sizes: CSV 179.25 / 175.52 MiB, Parquet
  124.45 / 122.50 MiB, NDJSON 165.09 / 161.50 MiB. Measurements include readers,
  validation, spool, JSON adaptation, driver and commit, excluding server memory.
  [Aggregate results and individual runs](../benchmarks/results/import-2026-09-10.json)
  record exact versions, ranges and timings. The new isolated CI job repeats
  the complete gate and publishes aggregate-only evidence.
- COPY's 100,000-row Parquet median was 17.46 seconds versus 18.60 for pipeline
  inserts (about 6% faster). Pipeline remains the CLI default: the end-to-end
  gain is modest and COPY FROM is not compatible with applicable row-level
  security. The benchmark uses only disposable synthetic tables owned by its
  test role, not weakened application permissions.
- Phase 3 final local checks: 137 Python tests (including both real-database
  suites), 58 frontend tests and 14 desktop/mobile browser tests passed; type,
  lint, format, data-leak and whitespace checks passed. The frontend is unchanged
  at 59.46 KiB gzip. Phase push and remote CI/deployment verification follow.
