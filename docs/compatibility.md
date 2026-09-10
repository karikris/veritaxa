# Compatibility and retirement

The September efficiency refactor removes unused application code, not review
history or support for unidentified deployed clients. The following compatibility
surface remains deliberately supported until its retirement conditions are met.

## Review RPCs

The current browser calls `list_review_batches`, `get_review_cursor`, and
`save_image_review_v2`. The following older endpoints remain in the database:

- `public.get_review_queue(uuid, integer)`
- `public.submit_image_review(uuid, public.review_label, text, uuid, text)`

Repository searches find no current browser calls to either legacy endpoint.
Their generated database types describe the actual database and are not runtime
calls. The security suite still exercises authenticated legacy submissions,
idempotent retries, authorization and restricted queue responses.

Source absence and a successful deployment do **not** establish a usage cutoff.
An already open browser tab can retain an older bundle; external clients are not
enumerated by this repository. No complete production request-log window or
owner-approved minimum-client policy has been established by this refactor.
Current review rows and their `client_version` are not an access log: they cannot
show queue reads, failed calls or inactive clients that will return later.

Retirement requires:

1. An explicit supported-client cutoff and a refresh/migration notice for affected
   reviewers and external clients. Do not assume a particular inactivity period
   proves that a browser tab no longer exists.
2. Verification that supported deployments use the current RPCs, plus a reviewed
   observation window for both legacy endpoints if continued compatibility is
   required. Record coverage gaps and errors; absent or reset statistics are not
   evidence of zero use. Keep raw request logs and reviewer data private.
3. A new forward migration dropping only the exact retired signatures, without
   `CASCADE`. Update generated types and replace the legacy execution tests with
   absence assertions. Run the current auth, ownership, retry, correction and
   cursor suites against a freshly migrated database before release.
4. A separately reviewed rollout and recovery procedure. Do not edit applied
   migrations, delete reviews, or revoke current RPC grants to perform retirement.

No legacy endpoint is removed merely to make this checklist appear complete.

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
