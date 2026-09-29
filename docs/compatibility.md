# Compatibility and retirement

The September efficiency refactor removes obsolete APIs and unused application
code, not review history, provenance or historical label meanings.

## Review RPCs

### Unreviewed-only workflow

The September 29 update uses `list_pending_review_batches`,
`get_pending_review_cursor` and `save_pending_image_review`. These exclude images
already reviewed by anyone, matching source provider plus image ID across all
campaigns and batches. Refresh the website to use the new queues; existing tabs
are not forcibly reloaded, so their unsaved drafts are preserved.

The earlier owner-scoped cursor and save APIs remain available for saved-answer
comparison, pending retries and corrections. A successful pending save may return
an empty array when the dataset is exhausted; clients must refresh the dataset
list instead of treating that response as a failed write. No historical items,
reviews or datasets are deleted or relabeled by this update.

Verified against PostgreSQL's [function snapshot rules](https://www.postgresql.org/docs/current/xfunc-volatility.html),
[transaction advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS),
and PostgREST's [empty-rowset RPC test](https://github.com/PostgREST/postgrest/blob/33823088dab1ab2953e85c3f3cde306fec0b008b/test/spec/Feature/Query/RpcSpec.hs#L471-L478)
using GitHits. Advisory locking covers the pending-save endpoint; compatibility
clients must refresh to use this endpoint and the global queue rules.

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
