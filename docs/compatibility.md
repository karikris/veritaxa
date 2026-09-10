# Compatibility and retirement

The September efficiency refactor removes obsolete APIs and unused application
code, not review history, provenance or historical label meanings.

## Review RPCs

On 11 September 2026 the owner explicitly ended support for older deployed
clients. The deployed release at commit `05e7dec54a3ae5ef1d5c5c2fa21347eaf984553f`
is the minimum supported client. **Users of stale browser bundles must refresh
the application before continuing.** External clients must migrate to the current
RPCs: `list_review_batches`, `get_review_cursor`, and `save_image_review_v2`.

The [forward retirement migration](../supabase/migrations/20260910212342_retire_legacy_review_rpcs.sql)
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
