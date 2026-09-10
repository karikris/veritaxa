# September efficiency implementation

User direction: backlog ButterflyLens, implement the VeriTaxa review plan,
commit each focused change and push after each verified phase. Only VeriTaxa
application code is in scope. Existing ButterflyLens edits remain untouched.

Baseline: `50b69126d4a52edbfbbbae57704b78ede2b35dbb`. Local main was clean and
fast-forwarded from `a390030` before implementation. The full private audit and
reproduction artifacts remain outside this public-code repository.

## Phases and evidence

| Phase | Required result                                                                                             | Status                         |
| ----- | ----------------------------------------------------------------------------------------------------------- | ------------------------------ |
| 0     | Current baseline, synthetic profiling harness, preservation contracts                                       | Verified and pushed            |
| 1     | Session/image ownership, versioned drafts, immutable retry payloads, typed conflicts, Unicode parity        | Verified and pushed            |
| 2     | Bounded export/consensus, full and explicit lean projection, atomic output                                  | Verified and pushed            |
| 3     | Bounded import/validated spool, metadata preservation, deterministic shuffle, atomic publish                | Verified and pushed            |
| 4     | Stable DOM, bounded drafts, explicit display/full-resolution policy, browser soak                           | Locally verified; push pending |
| 5     | Forward cursor-seek migration, pgTAP edge cases, measured local plans                                       | Pending                        |
| 6     | Dead-code removal, consolidated capabilities/normalization, Python/schema parity, safe compatibility cutoff | Pending                        |

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
- Phase 3 pushed through `0e67929`. GitHub rejected CI `34483253598` before
  starting jobs because `runner.temp` is unavailable in job-level `env`. The
  fixture path now names a fixed temporary directory on the disposable runner;
  generation still refuses to overwrite any existing fixture. This focused CI
  correction requires a new push/run, not a passing claim for the rejected run.
- Phase 3 correction `cf32f8d` is pushed. [CI 34483467128](https://github.com/karikris/veritaxa/actions/runs/34483467128)
  passed all four jobs: application, Supabase security, full export memory and
  full import memory. The downloaded import artifact confirms 42 fresh-process
  runs passed on Python 3.12.3 / PostgreSQL 17.11: largest RSS 215.79 MiB and
  largest median growth 18.51 MiB. For 100,000-row Parquet, pipeline took a
  43.74-second median and COPY 44.33 seconds; CI showed no COPY speed advantage.
  [Pages 34485932827](https://github.com/karikris/veritaxa/actions/runs/34485932827)
  passed at the same pushed commit. Phase 3 is verified and deployed; phase 4
  commits below remain local until that phase's remaining gates pass.
- Phase 4 stable-view foundation: the application shell, batch selector, review
  controls and classification inputs persist through ordinary edits and status
  updates. An owned image node persists through label/comment/save-status changes
  and fallback URLs; a genuinely new attempt gets a new node, and the previous
  source and error handler are explicitly released. Session reset and disposal
  release the view. Task values enter static markup only through text/value
  properties or the existing validated image URL path, never HTML interpolation.
- Stable-view checks pass 61 frontend tests and 16 desktop/mobile browser tests,
  including exact node identity, retained focus/caret/zoom, no new image requests
  from ordinary edits, detached-image errors, retries, conflicts and initial
  cursor-error recovery. Lint/type/format checks and the 60.53 KiB gzip bundle gate
  pass. These are correctness/allocation-churn regressions, **not** the required
  1,000-navigation heap/process-memory soak. Bounded dirty drafts and explicit
  preview/original policy are still required before phase 4 is complete.
- Phase 4 draft retention now uses byte-accounted parked snapshots. The total
  256-entry / 1 MiB budget reserves one slot and 16 KiB for the current editor,
  covering two maximally escaped 1,000-code-point comments plus request fields.
  Capacity blocks navigation and batch changes without eviction; explicit save
  or local discard resolves it. Unknown writes retain their immutable request
  and cannot be discarded. Snapshots prevent later edits after failed navigation
  from invalidating stored byte accounting. Restore/delete/session reset release
  the corresponding accounting and records.
- Draft-budget checks pass 68 frontend tests and 20 desktop/mobile browser tests.
  They exercise independent count/byte limits, escaped metadata-free comments,
  retained older drafts, batch-switch prevention, save/discard/retry decisions
  and the active-editor reserve. A navigation-only synthetic fixture generates
  one item on demand instead of allocating an artificial thousand-item queue.
  Type/lint/format checks and a 61.09 KiB gzip bundle pass. Preview/original policy
  and measured long-session JS/image/process-memory gates are still pending.
- Phase 4 image policy separates supplied previews from explicit source
  inspection. Valid supplied Flickr renditions at most 1,600 pixels are accepted;
  larger/original secrets are never transformed into guessed size URLs. A
  distinct unknown-provider display URL is an upstream preview declaration, not
  a dimension guarantee. Missing/duplicated unknown previews require explicit
  source inspection; automatic fallback uses only a supplied bounded rendition.
  Returning to preview, moving to another item and resetting the session release
  the prior source/handlers. Oversized previews are released after load, with
  their initial decode peak explicitly outside a hard memory guarantee.
- Image-policy checks cover 87 frontend tests and 24 desktop/mobile browser
  cases, including source inspection without losing drafts, preview retry,
  post-load size checks, native fallback, stale load/error callbacks, and locked
  saves. The privacy scanner now permits a bare provider configuration hostname
  while rejecting literal/escaped/encoded source paths; an isolated synthetic Git
  fixture tests that distinction and the retained private-data markers. No task
  URLs, original-image binaries, live database changes or image mirror are added.
  The real-raster long-session memory gate remains required before phase 4 ends.
- Phase 4 browser-memory harness `5ed5409` exercises the production application
  with a synthetic on-demand repository and real, distinct 1,600 × 1,067 PNGs.
  The gate runs 1,000 navigations in each of nine fresh browser processes:
  three desktop, three draft-heavy and three mobile-pressure. It checks retained
  heap/DOM, all browser descendant process RSS/PSS, detailed decoded-image/GPU
  allocations, explicit original inspection and cached return to preview.
  Each draft-heavy run resolves capacity explicitly 745 times without evicting
  older drafts. The CI job repeats the gate independently of interaction tests.
- Controlled investigation found that network recording itself caused native
  allocation growth even in an image-only page: direct CDP plus `Network.enable`
  grew partition allocations from 70.70 to 202.31 MiB between navigations 300
  and 1,000. Without recording this pool stayed around 5–7 MiB. The measured
  harness therefore avoids network recording while leaving HTTP/image caches
  enabled. The negative control remains available and cannot count as a pass.
- The first nine-run suite had passing memory measurements but failed overall
  because one browser profile directory was still being written during cleanup.
  Graceful `Browser.close`, bounded shutdown fallbacks and retrying removal of
  the owned temporary directory fixed that race. A thread-exit sampling regression
  also ensures a closing child cannot erase a live parent's process footprint.
  The complete rerun passed all nine processes with clean shutdowns. The eight
  harness tests include invalid/missing evidence and native-growth failure cases.
- Final local [browser measurements](../benchmarks/results/browser-2026-09-11.json)
  preserve all 99 checkpoints, source calibrations, versions, individual gates,
  three-run medians and ranges. Maximum retained JS heap was 0.962 MiB; maximum
  fitted post-warm-up heap growth was 0.062 MiB. Decoded-image fitted growth was
  at most 6.516 MiB; process PSS median and fitted growth were negative in every
  run. Retained document/node/listener counts stayed fixed. These are bounded
  growth results, **not** a small total-RAM claim: desktop decoded-image accounting
  reached 514.73 MiB and whole-browser post-GC PSS reached 1,064.83 MiB on this
  host. Mobile viewport/touch emulation, a 64 MiB V8 old-space limit and synthetic
  critical pressure are not a physical low-RAM phone or total-process RAM cap.
  [Methodology and limitations](../benchmarks/browser-memory.md) distinguish
  allocation accounting, resident memory, pre-GC peaks and original-image limits.
- Final phase 4 local checks pass 87 frontend tests, 24 desktop/mobile interaction
  tests, eight harness tests, 137 Python tests using disposable local databases,
  type/lint/format/Ruff/data-leak/whitespace checks and the production build.
  JavaScript is 61.96 KiB gzip. The bundle checker now actually enforces the
  planned 70 KiB ceiling (previously 250 KiB), with a regression test that also
  rejects a missing or empty build. Remote CI and deployment remain unverified
  until the phase is pushed and those runs finish.
- Phase 5 preparation only: all nine existing migrations and all 54 existing
  pgTAP assertions passed on a disposable PostgreSQL 18.3 database with a minimal
  local Auth table/claim-function fixture. Supabase CLI advisors reported no
  issues. This is SQL-only verification, not an Auth service test or a live
  Supabase migration. Cursor optimization and its new regression tests remain
  to be implemented.
