# September efficiency implementation

User direction: backlog ButterflyLens, implement the VeriTaxa review plan,
commit each focused change and push after each verified phase. Only VeriTaxa
application code is in scope. Existing ButterflyLens edits remain untouched.

Baseline: `50b69126d4a52edbfbbbae57704b78ede2b35dbb`. Local main was clean and
fast-forwarded from `a390030` before implementation. The full private audit and
reproduction artifacts remain outside this public-code repository.

## Phases and evidence

| Phase | Required result                                                                                             | Status                               |
| ----- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| 0     | Current baseline, synthetic profiling harness, preservation contracts                                       | Verified and pushed                  |
| 1     | Session/image ownership, versioned drafts, immutable retry payloads, typed conflicts, Unicode parity        | Local checks passed; CI follows push |
| 2     | Bounded export/consensus, full and explicit lean projection, atomic output                                  | Pending                              |
| 3     | Bounded import/validated spool, metadata preservation, deterministic shuffle, atomic publish                | Pending                              |
| 4     | Stable DOM, bounded drafts, explicit display/full-resolution policy, browser soak                           | Pending                              |
| 5     | Forward cursor-seek migration, pgTAP edge cases, measured local plans                                       | Pending                              |
| 6     | Dead-code removal, consolidated capabilities/normalization, Python/schema parity, safe compatibility cutoff | Pending                              |

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
