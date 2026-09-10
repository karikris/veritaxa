# September plan: verification map

This maps the review plan's requirements to implementation and evidence, rather
than treating a green unit-test total as proof of memory bounds or data integrity.
[Implementation history](implementation.md) records phase commits and measured
results. [CI](https://github.com/karikris/veritaxa/actions/workflows/ci.yml) and
[Pages](https://github.com/karikris/veritaxa/actions/workflows/pages.yml) provide
independent results; check the exact tested and checked-out source commit.

## Requirement evidence

| Requirement                            | Implementation and verification                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Baseline and scope                     | Work started from remote `50b6912`; `fe3ad91` retains synthetic baseline probes and preservation contracts. ButterflyLens remains externally backlogged and was not modified by this implementation. No real tasks or original audit exports are published.                                                                                                                                                                                                                              |
| Session and callback ownership         | [App coordinator](../src/app.ts) owns session epochs, request IDs and image/view identities. [App regressions](../src/app.test.ts) cover delayed save success/failure after sign-out, account replacement and disposal; stale initial session restore; detached image load/error callbacks; and save locks during image failure.                                                                                                                                                         |
| Versioned drafts and immutable retries | [Draft model](../src/domain/reviewDraft.ts) keeps base version and frozen pending request together. App regressions verify external corrections, retained original request identity after further edits/navigation, fresh IDs for subsequent changes, both typed conflicts, comparison/reapply, and accepting saved answers without a write.                                                                                                                                             |
| Unicode parity                         | [Text helpers](../src/domain/text.ts), [submission normalization](../src/domain/reviewQueue.ts) and [RPC parser](../src/data/supabaseReviewRepository.ts) use code-point limits. Tests cover 1,000/1,001 astral characters, combining sequences, truncation, response validation and reuse of counts during unchanged view updates.                                                                                                                                                      |
| Shared execution permissions           | App capabilities drive handlers and controls. Tests dispatch queued/programmatic events during save/load and alter disabled DOM properties without gaining permission. Failed initial cursor reads now enter an error state: retry or batch change is possible, but a running recovery cannot be duplicated.                                                                                                                                                                             |
| Bounded export and consensus           | [Exporter](../tools/export_reviews.py) uses libpq single-row streaming, a read-only repeatable-read snapshot and SQL vote aggregation before fetching metadata once per output item. [Real-driver tests](../tools/tests/test_export_database.py) cover types, nulls, canonical JSON, full/lean projections, raw/consensus order, votes, timestamps, concurrent edits, cancellation and failed writes.                                                                                    |
| Atomic CSV/Parquet output              | [Writer](../tools/tabular_output.py) stages privately and publishes only on successful completion. [Writer tests](../tools/tests/test_tabular_output.py) check empty schema, null versus empty string, Unicode, late source failure, publication failure, row/byte batch limits and non-retention of bulky Parquet statistics.                                                                                                                                                           |
| Bounded import with preserved metadata | [Readers](../tools/candidate_input.py) and [validated spool](../tools/candidate_spool.py) replace whole-input CLI plans. [Reader tests](../tools/tests/test_candidate_input.py) compare legacy types across formats/chunk boundaries, preserve unknown and late nested fields, detect changed inputs and reject invalid rows before resolving credentials.                                                                                                                               |
| Import order, seed 0 and atomicity     | [Spool tests](../tools/tests/test_candidate_spool.py) verify logical positions independently of byte chunks, global `sha256-v1` seed ordering, duplicate membership rules, cleanup and oversized-row handling. [Database tests](../tools/tests/test_import_database.py) compare every inserted field and prove rollback after late stream, constraint and count failures; another connection cannot observe partial publication.                                                         |
| COPY decision and dependency gate      | [Admin measurements](../benchmarks/README.md) include full pipeline-versus-COPY comparisons, not an assumed benefit. Pipeline insertion remains the CLI default. PyArrow was added only after the existing-stack Parquet path exceeded the memory budget; Polars remains for compatible input inference, pinned to tested non-yanked 1.43.2.                                                                                                                                             |
| Stable DOM and bounded drafts          | [Review view](../src/view/reviewView.ts) retains ordinary image/control nodes; [draft store](../src/domain/draftStore.ts) reserves the active editor within 256 entries and 1 MiB. Unit and [desktop/mobile browser tests](../tests/e2e/review-flow.spec.ts) cover identity, focus/caret/zoom, draft count/bytes, explicit save/discard/retry resolution and no silent eviction.                                                                                                         |
| Display image policy                   | [Image policy](../src/image/imagePolicy.ts) and [loader](../src/image/imageLoader.ts) prefer supported bounded previews; original inspection is explicit. Tests cover provider/lookalike URLs, fallback, oversized-preview release, source/preview transitions and stale callbacks. No image mirror or automatic uncontrolled-original fallback was introduced.                                                                                                                          |
| Browser scaling                        | [Real-raster soak](../benchmarks/browser-memory.md) checks 1,000 navigations in nine fresh browser processes: desktop, draft-heavy and mobile-pressure, three repeats each. Gates inspect JS heap, DOM, all browser-process RSS/PSS and native image/GPU allocations, plus explicit original requests and cached preview return.                                                                                                                                                         |
| Indexed cursor selection               | The [forward seek migration](../supabase/migrations/20260910151534_seek_review_cursor_positions.sql) preserves authorization, response shape and exact progress. [48 cursor assertions](../supabase/tests/review_cursor.test.sql) cover range/gap/extreme anchors, wrap, empty/single/complete batches and independent reviewers. [Measured plans/timings](../benchmarks/cursor-database.md) separate indexed selection from full authenticated RPC p50/p95, including unchanged resume. |
| Schema, authorization and provenance   | All nine pre-refactor migrations and every historical label schema remain unchanged. [Security tests](../supabase/tests/review_security.test.sql) preserve authorization, narrow RPCs, current-row ownership, idempotency, identity/deletion guards and version/time requirements. The renamed guard is checked structurally and behaviorally. Fresh SQL-only migration checks complement, but do not replace, the CI Supabase-service job.                                              |
| Legacy cleanup and label parity        | Unused prefetch, assertion, state, submission-ID and browser-priority helpers are removed; actual retry and consensus paths retain coverage. [Python parity](../tools/tests/test_label_schema.py) checks all retained labels, pairwise priority ties and eager/streaming mappings. Existing TypeScript/schema parity remains; no per-operation schema-file loading is added.                                                                                                             |
| Bundle and private-data boundaries     | [Bundle gate](../scripts/check-bundle-size.mjs) enforces 70 KiB gzip and rejects missing/empty builds. [Data scan](../scripts/check-no-review-data.mjs) checks source and production output, including encoded private-data markers. Synthetic repository selection is development-only; the production app remains framework-free.                                                                                                                                                      |

## Measured budgets and limits

- Admin gates require every run at both 10,000 and 100,000 rows to stay at or
  below 256 MiB RSS, with at most 64 MiB growth between three-run medians. The
  [import](../benchmarks/results/import-phase6-2026-09-11.json) and
  [export](../benchmarks/results/export-phase6-2026-09-11.json) results include
  nested 20 KiB metadata and all reader/driver/writer components, not server RAM.
- Application insertion/writer chunks are capped at 1,000 rows or 4 MiB, with an
  accepted row up to 16 MiB processed alone. Reader/decoder and encoder buffers
  are accounted for separately. Accepted 8 MiB and rejected 17 MiB fixtures are
  correctness tests, not a claim that arbitrary oversized-input RSS stays below
  the 20 KiB-fixture budget.
- Browser gates bound retained growth, not total browser RAM. Native caches can
  be much larger than the JavaScript heap. Mobile pressure is emulated, not a
  physical low-RAM phone test. Uncontrolled originals and the first decode of an
  oversized declared preview do not have a hard RAM guarantee.
- Exact progress counting still scales with batch size; no constant-time full
  RPC or resume speedup is claimed. Native cache accounting is not additive to
  process memory. Runtime versions, individual runs and ranges remain in reports.

## Legacy API retirement

The owner established the deployed `05e7dec` release as the minimum supported
client and ended legacy-client support on 11 September 2026. Stale browser bundles
must refresh before continuing; external clients must migrate to current RPCs.
The [retirement migration](../supabase/migrations/20260910212342_retire_legacy_review_rpcs.sql)
drops only the exact old queue/submit signatures without `CASCADE`. Security tests
assert their absence and preserve useful validation/retry checks on the current
save API. [Compatibility policy](compatibility.md) records rollout, recovery and
the explicit boundary preserving reviews, schema/label versions, client-version
history, source metadata and applied migrations. Live application must be verified
separately; local checks and Pages deployment do not change the live database.
