# Compatibility and retirement

## Backend dependency review — 30 September 2026

The monthly update covers the local Python administration tools and the Supabase
CLI. Exact versions and artifact hashes are recorded in `uv.lock` and
`package-lock.json`. It does not change the hosted database engine or schema.

This section records the initial backend upgrade. The subsequent
[security follow-up](dependency-security.md) addresses the remaining native TLS
and frontend-tooling findings below.

| Dependency                                | Previous | Selected | Decision                                                      |
| ----------------------------------------- | -------- | -------- | ------------------------------------------------------------- |
| Polars / polars-runtime-32                | 1.43.2   | 1.44.2   | Update together; data conversion and correctness fixes        |
| Psycopg / psycopg-binary                  | 3.3.4    | 3.3.6    | Update together; cancellation, COPY and bundled-library fixes |
| Ruff                                      | 0.16.0   | 0.16.9   | Update Python development tooling                             |
| Supabase CLI, including platform packages | 2.109.1  | 2.118.0  | Update database development tooling                           |
| jose, through Supabase CLI                | 6.2.4    | 6.2.12   | New CLI constraint resolves to this reviewed patch            |
| PyArrow                                   | 25.0.1   | 25.0.1   | Already the latest stable release reported by GitHits         |
| pytest                                    | 9.1.1    | 9.1.1    | Already the latest stable release reported by GitHits         |

### Evidence and compatibility

GitHits `pkg_info`, batched `pkg_upgrade_review`, `pkg_changelog`, and pinned
`pkg_vulns` checks covered the selected packages and Python lockfile dependencies.
`search` / `search_status`, `code_grep`, and `read` inspected the upstream release
tags. GitHits returned empty package release-note bodies for Psycopg and the CLI;
the repository release history and tagged source supplied the missing evidence.
Advisory results describe package versions, not proof that vulnerable code is
reachable or a complete audit of native libraries embedded in wheels/binaries.

- **Polars:** [1.44.0 notes](https://github.com/pola-rs/polars/releases/tag/py-1.44.0)
  deprecate explicit reader/scanner `rechunk` arguments and `Expr.rechunk()`.
  VeriTaxa uses neither. The
  [NDJSON implementation](https://github.com/pola-rs/polars/blob/py-1.44.2/py-polars/src/polars/io/ndjson.py#L163-L204)
  confirms that omitting `rechunk` retains `False`, and continues forwarding
  `schema`, `batch_size`, and `low_memory`. Arrow nested-list/map conversions and
  Parquet reading receive correctness fixes. Sparse patch notes were supplemented
  with the [1.44.0–1.44.2 source history](https://github.com/pola-rs/polars/compare/py-1.44.0...py-1.44.2):
  null-mask/broadcasting fixes, concatenated gzip Parquet support, and reduced
  Parquet fsync overhead. Production exports retain their own fsync and atomic
  rename in `tools/tabular_output.py` and use PyArrow for Parquet writing.
- **Psycopg:** [tagged release notes](https://github.com/psycopg/psycopg/blob/3.3.6/docs/news.rst#L13-L47)
  cover prepared-statement invalidation, malformed COPY data raising `DataError`,
  and bounded cancellation. Source inspection of
  [Connection.wait](https://github.com/psycopg/psycopg/blob/3.3.6/psycopg/psycopg/connection.py#L479-L516)
  confirms cancellation waits are bounded and an unresponsive connection is
  closed. This needs libpq 17+, satisfied by the selected binary wheel. Existing
  handlers catch `psycopg.Error`; tuple/dict rows do not depend on the changed
  `namedtuple_row` duplicate-column exception or interval precision metadata.
- **Ruff:** [release history](https://github.com/astral-sh/ruff/releases)
  fixes false positives, unsafe autofixes, and obsolete `UP035` recommendations.
  Our Python 3.12 target and explicit rule families remain unchanged; preview
  rules are not enabled. Both lint and formatting pass without source edits.
- **Supabase CLI:** [2.118.0 notes](https://github.com/supabase/cli/releases/tag/v2.118.0)
  include startup/reset fixes, root-bounded content paths, exact `--workdir`
  handling, and consent fixes. `storage rm` now needs explicit confirmation.
  Automation using those operations should check its consent handling. Our CI
  uses `start`, `db lint`, and `test db`; these commands and flags still exist.
  The new experimental stack is opt-in: the
  [init implementation](https://github.com/supabase/cli/blob/v2.118.0/apps/cli/src/commands/init/init.handler.ts#L26-L42)
  defaults its configuration value to false. Existing Postgres 17 configuration
  remains unchanged.
- **jose:** [6.2.5–6.2.12 changes](https://github.com/panva/jose/blob/505a55b8f73536082367b2614cb77e927ba96ec1/CHANGELOG.md)
  tighten malformed JWT/JWE/JWK input validation and improve key-import and
  serialization performance. The CLI's
  [JWT verification paths](https://github.com/supabase/cli/blob/v2.118.0/apps/cli/src/shared/functions/serve.main.ts#L290-L323)
  use ordinary secret/JWKS verification and map verification failures to auth
  errors. Nonstandard tokens accepted by older versions may now be rejected.

### Security fixes and remaining exposure

GitHits found no direct affected advisories for the selected Python package
versions or Supabase CLI/jose. This does **not** mean all native code is patched.
The Psycopg wheel build pins change from
[libpq 18.0 / OpenSSL 3.5.4](https://github.com/psycopg/psycopg/blob/3.3.4/.github/workflows/packages-bin.yml#L18-L28)
to [libpq 18.6 / OpenSSL 3.5.8](https://github.com/psycopg/psycopg/blob/3.3.6/.github/workflows/packages-bin.yml#L18-L28).
Runtime inspection of the installed Linux wheel confirmed libpq 18.6 and
OpenSSL 3.5.8. Windows builds obtain libpq differently; verify their installed
libraries separately before claiming identical native security coverage.

- **Fixed in the selected wheel:**
  [CVE-2025-12818](https://www.postgresql.org/support/security/CVE-2025-12818/)
  affects libpq allocation arithmetic before 18.1 and can crash a client.
  [CVE-2026-6477](https://www.postgresql.org/support/security/CVE-2026-6477/)
  affects libpq large-object functions before 18.4; VeriTaxa has no `lo_*` calls.
  Both affected library versions were bundled previously and are now replaced.
- **OpenSSL fixes:** 3.5.8 includes earlier TLS certificate-compression and
  CMS/PKCS7 memory-safety fixes, including CVE-2025-66199, CVE-2025-15467 and
  CVE-2026-45447. CMS/PKCS7 processing is not used by these administration tools.
  See the [upstream affected-version list](https://openssl-library.org/news/vulnerabilities-3.5/).
- **Still open:** OpenSSL advisories published on 29 September require 3.5.9.
  In particular,
  [CVE-2026-35189](https://openssl-library.org/news/vulnerabilities-3.5/#CVE-2026-35189)
  permits excessive allocation while processing a peer certificate, relevant
  to a TLS database client. Other new issues concern QUIC, DTLS, CMP and signing
  configurations outside our normal PostgreSQL connection path. The latest
  available Psycopg binary release still bundles 3.5.8. Follow up with a rebuilt
  upstream wheel, or a separately tested system-linked installation using
  patched libpq/OpenSSL. A system OpenSSL update alone does not replace the
  wheel's bundled copy.
- **Already fixed before this update:** PyArrow 25.0.1 is outside the affected
  range for [CVE-2026-25087](https://github.com/advisories/GHSA-rgxp-2hwp-jwgg)
  (fixed in 23.0.1) and CVE-2023-47248 (fixed in 14.0.1). pytest 9.1.1 is outside
  the affected range for [CVE-2025-71176](https://github.com/advisories/GHSA-6w46-j5rx-g56g)
  (fixed in 9.0.3). These are not security fixes delivered by this update.

The initial npm lockfile audit reported six affected development-package
entries (three high, three moderate), outside the backend upgrade set:

| Installed dependency                               | Path / issue                                                                                                                                            | Fixed version                               |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| vitest, @vitest/mocker, @vitest/coverage-v8 4.1.10 | [Mock redirect path traversal](https://github.com/advisories/GHSA-82fw-gwwq-j7x9)                                                                       | 4.1.11, update Vitest and coverage together |
| brace-expansion 5.0.8                              | ESLint/minimatch; multiple CPU, memory and recursion DoS advisories, including [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) | 5.0.12 covers all reported ranges           |
| nanoid 3.3.16                                      | Vite/PostCSS; [zero-size custom generator loop](https://github.com/advisories/GHSA-2v37-7h3g-55p8)                                                      | 3.3.18                                      |
| undici 7.29.0                                      | jsdom; TLS validation, WebSocket/HTTP DoS, cache and retry issues, including [GHSA-w293-vg96-wgc3](https://github.com/advisories/GHSA-w293-vg96-wgc3)   | 7.29.1                                      |

These were separated into follow-up frontend/tooling work. Their presence in development
dependencies does not establish browser-production exploitability. No forced
or unreviewed broad npm audit fix was applied.

### Validation

Python 3.12 and 3.14: all 143 tests passed (107 unit tests and 36 database
integration tests). Integration tests used fresh disposable local PostgreSQL
databases and cover streaming
exports, pipeline/COPY import parity, rollback and interruption handling.
Ruff lint and format checks pass. The selected CLI starts, reports 2.118.0,
parses the existing project configuration, and executes a query against the
disposable database. Full Docker-backed Supabase startup and pgTAP testing
could not run locally because access to `/var/run/docker.sock` is denied;
the existing CI database job must verify that service-level integration.
Lockfile consistency, installed Python dependency compatibility, the private-data
scan and `git diff --check` pass. `npm audit --omit=dev` reports no affected
production packages; the full development findings above were open at that point.

## September efficiency refactor

The September efficiency refactor removes obsolete APIs and unused application
code, not review history, provenance or historical label meanings.

## Review RPCs

### Dataset refresh with unchanged review workflow

A subsequent September 29 refresh archives the next set of completed reviews
using the same preservation checks, and publishes only their remaining unreviewed
images. Original review rows stay in the same historical store. The chooser now
groups dataset codes by A, B, C series before code sequence, so replacement
datasets appear alongside their series. New answers remain navigable and editable
until a later explicit refresh.

The September 29 refresh reduces the published datasets once, excluding images
already reviewed by anyone at publication time. Identity is source provider plus
image ID across all campaigns and batches. Affected batches are closed and their
remaining images published in replacement batches; unaffected batches retain
their IDs. Original items, metadata and review records remain intact.

The browser uses `list_review_batches`, `get_review_cursor` and
`save_image_review_v2`. Previous/Next visits all images in a published dataset,
including saved answers. Progress remains per reviewer; completed datasets stay
available and answers can still be corrected. Later reviews do not shrink the
available data. Refresh the website to load the updated dataset list.

The short-lived `list_pending_review_batches`, `get_pending_review_cursor` and
`save_pending_image_review` endpoints delegate to the original APIs through a
forward migration, so existing browser bundles also regain the original behavior.
They no longer filter reviewed images, reject another reviewer's submission, or
return an empty cursor on completion. Earlier applied migrations are retained.

The refresh locks review tables for its transaction to keep the selection and
publication consistent. The locking behavior was checked using GitHits against
PostgreSQL's [LOCK documentation](https://www.postgresql.org/docs/current/sql-lock.html).
The lock is inside the atomic `DO` statement so CLI replay also works when
top-level statements run in separate transactions. This placement repair does
not change the already-applied data refresh, RPC definitions or migration version.

The applied migration's three `BEGIN ATOMIC` calls quote the private function
identifiers for CLI replay compatibility. This is a lexical-only repair: the
CLI's [statement splitter](https://github.com/supabase/cli/blob/997a1e69a4a83466964ed874d3a604c88a7b3866/apps/cli-go/pkg/parser/state.go#L197-L207)
otherwise mistakes the `end` in `pending` for the body terminator. Quoting the
same lowercase identifiers preserves the bound functions, schema and permissions;
the hosted database already has those definitions. No migration version or
historical data is changed.

### Earlier API retirement

On 11 September 2026 the owner explicitly ended support for older deployed
clients. The deployed release at commit `05e7dec54a3ae5ef1d5c5c2fa21347eaf984553f`
is the minimum supported client. **Users of stale browser bundles must refresh
the application before continuing.** External clients must migrate to the current
RPCs: `list_review_batches`, `get_review_cursor`, and `save_image_review_v2`.

The [forward retirement migration](../supabase/migrations/20260914092659_retire_legacy_review_rpcs.sql)
removes only these two exact API signatures:

- `public.get_review_queue(uuid, integer)`
- `public.submit_image_review(uuid, public.review_label, text, uuid, text)`

This is an explicit support-policy cutoff, not an inference of zero legacy use.
The minimum release has no calls to the retired APIs; its successful
[deployment](https://github.com/karikris/veritaxa/actions/runs/34503930381) checked
out that exact commit, and the served assets matched the deployment artifact.
`client_version` values remain historical data, not evidence that all old tabs
have closed. Retirement does not depend on proving zero usage because older
clients are now explicitly unsupported.

The migration uses one atomic `DROP FUNCTION ... RESTRICT` statement, without
`CASCADE`. Unexpected dependencies must abort removal, not be deleted. Current
RPCs, grants, RLS and ownership/version checks remain unchanged. Database types
omit the removed endpoints. Security tests assert their absence and exercise
normalization, identity, retry, validation and correction through the current API.

Live retirement was verified on 14 September 2026. Both functions are absent
from the catalog and both public API routes return HTTP 404 / `PGRST202` with
their former argument names. Review and source-metadata fingerprints, current
RPC definitions/grants, review-table structure and the nine prior migration
entries matched before and after removal. No historical records were exported.

### Data-preservation boundary

Do not remove or rewrite historical `image_reviews`, old schema versions, old
label meanings, `client_version` history, source metadata or applied migrations.
Existing review rows remain current/versioned records; this retirement neither
deletes them nor invents a revision history that the database never stored.

### Rollout and recovery

1. Publish this refresh/migration notice and verify the minimum supported client
   uses only current RPCs. Do not force-refresh a user's unsaved draft.
2. Test the complete migration chain and current auth, ownership, retry,
   correction and cursor suites. Check an upgrade against existing synthetic
   records, definitions and grants before touching the live database.
3. Verify the live project's identity, migration history and exact signatures.
   Apply the retirement migration only after those checks; a Git push or Pages
   deployment does not apply database migrations. Do not automatically apply
   unrelated pending migrations as part of retiring these endpoints.
4. Confirm both legacy endpoints are absent and current RPCs/grants remain intact.
   Recovery is refresh/migration to the supported client. If the owner later
   reverses the support policy, restore only the required definitions and exact
   grants from retained migration history in a new reviewed forward migration;
   never roll back or delete review data or edit applied migrations.

Supabase assigned the retirement version `20260914092659` when applying it. The
previously pending repository file was renamed to match that new entry, with
identical SQL; no previously applied production migration was renamed or edited.
The cursor-seek and identity-guard rename were left pending at that retirement
step. The owner subsequently authorized their separate rollout: they were
applied as `20260914134310` and `20260914134318`, with their pending repository
files renamed to match and SQL unchanged. All previously applied production
migration files and history entries were retained.

## Current RPC security boundary

The [security migration](../supabase/migrations/20260914134325_harden_review_rpc_boundaries.sql)
keeps all supported public function names, arguments, results and reviewer
authorization behavior. Privileged implementations now live in `private`;
public functions are security-invoker entry points with definition-time-bound
SQL bodies. The existing implementations were moved, not copied or rewritten.
Do not replace those bodies with late-parsed strings or grant browser roles
private-schema usage: the explicit binding lets the same API work while private
object lookup and direct table access remain denied.

All six VeriTaxa tables have explicit restrictive rejection policies for browser
roles. These preserve the existing RPC-only access model and guard against a
future accidental permissive policy. The optional hosted `rls_auto_enable`
maintenance function retains its definition and event trigger, but no longer
grants execution to `PUBLIC`, `anon` or `authenticated`.

Live security advisors now report no VeriTaxa database findings. Five informational
no-policy notices belong to separate BioMiner tables in the shared project and
were not modified. The remaining Auth warning is leaked-password protection:
Supabase requires Pro or higher, while this project is on Free. No billing plan,
login provider, user record or password setting was changed to hide that warning.

## Python helpers and historical data

The bounded import/export CLI paths are the supported large-data entry points.
The eager frame/plan helpers remain explicit small-input compatibility APIs and
golden-equivalence/baseline test references. Do not call them from the streaming
CLI or describe their memory usage as bounded. Removing them requires a separate
consumer check and moving their independent baseline oracle into test support.

Versioned label schemas, old label meanings, applied migrations, RPC-boundary
validation, database constraints and private historical reviewer records are not
dead code. Python/schema parity tests cover every retained label version, including
the legacy Flickr meaning; runtime code need not read the JSON schemas on each
operation. Removing private records or deduplicating campaign provenance is a
separate data-governance change, not part of this efficiency refactor.
