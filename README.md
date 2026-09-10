# VeriTaxa

VeriTaxa is a minimal, authenticated, one-page tool for recording broad human
labels against image candidates collected by BioMiner and related pipelines.
It shows one image at a time, saves one classification and an optional comment,
then advances atomically after Postgres confirms the write. Reviewers can move
through every image in a batch and revise their own current answer.

VeriTaxa is separate from ButterflyLens. ButterflyLens remains the
Australia-focused evidence and species-verification application; VeriTaxa is a
taxon-independent bulk image-triage tool.

Image-level labels describe what is visibly present. They are not bounding
boxes, segmentation masks, detector-ready localisation annotations,
species-level confirmations, or verified occurrence records.

## Architecture and privacy boundary

GitHub Pages hosts only the compiled static interface. Supabase stores private
campaigns, batches, source image URLs, hidden source metadata, the reviewer
profiles, and versioned current reviews. Authentication, active private profiles,
row-level security, and narrowly scoped security-definer RPC functions prevent
anonymous or suspended users from receiving task URLs or progress.

The browser uses a normal `<img>` element to download the displayed image
directly from its source host. There is no iframe, server image proxy, image
mirror, Supabase image transfer, or application-owned image store. Only the
image selected by the review cursor is requested.

Reviewer RPC responses contain only neutral batch details, progress, item IDs,
display/fallback URLs, and the campaign's target scientific name. The target is
shown as a classification option. Flickr retrieval keywords, other source
metadata, titles, tags, model outputs, confidence values, and previous reviews
remain in Postgres and never enter reviewer-facing responses or the DOM.

```text
GitHub Pages                         Supabase
static Vite application  ────────>  Auth + safe reviewer RPCs
        │                            private metadata + Postgres reviews
        └── direct HTTPS image request ──> source host

Local admin tools ────────────────> direct administrative Postgres connection
```

Parquet is supported for import and export, not as the live write store. Each
review is a small durable database write, and review progress can resume across
browsers without rewriting a dataset.

## Canonical labels

The stored schema version is `veritaxa-review-label-v3`. The granular code is
canonical; display labels and derived training groups are not stored as
redundant review columns.

| Stored code                | Display label                    |
| -------------------------- | -------------------------------- |
| `target_scientific_name`   | Current campaign scientific name |
| `adult_butterfly`          | Adult butterfly                  |
| `caterpillar`              | Caterpillar                      |
| `moth`                     | Moth                             |
| `other_insect`             | Other insect                     |
| `arachnid`                 | Spider or other arachnid         |
| `other_arthropod`          | Other arthropod                  |
| `plant`                    | Plant                            |
| `mammal_or_person`         | Mammal or person                 |
| `bird`                     | Bird                             |
| `other_animal`             | Other animal                     |
| `fungus`                   | Fungus                           |
| `artifact_or_illustration` | Object, artwork or illustration  |
| `no_biological_subject`    | No clear biological subject      |
| `uncertain`                | Uncertain                        |
| `image_unavailable`        | Image unavailable                |

Select the dynamic scientific-name option only when the visible subject is the
campaign's target taxon. Otherwise, for images with several subjects, choose
the most pipeline-relevant visible subject: adult butterfly, caterpillar, moth,
other insect, arachnid, other arthropod, mammal or person, bird, other animal,
plant, fungus, artifact, no clear biological subject, uncertain, then
unavailable. A real pinned butterfly is an adult butterfly; a butterfly
drawing, logo, toy, tattoo, or screenshot is an artifact.

The versioned definitions and pipeline mappings are in
`src/domain/reviewLabels.ts` and `schemas/review-labels-v3.json`.

## Database model and access

- `private.reviewer_profiles` stores each authenticated reviewer's UUID,
  submitted name, and active state outside the browser-accessible schema.
- New anonymous Auth users receive an active profile automatically without
  providing an email or password. Reviews snapshot the profile name in the
  requested dataset field `identifiedBy`.
- `review_campaigns` stores the target scientific name used by every item in
  that campaign.
- `review_batches` divides campaigns into neutral batches of at most 1,000
  items.
- `review_items` stores image URLs and source/pipeline metadata. Flickr
  retrieval keywords remain hidden from the browser.
- `image_reviews` stores one current, versioned response per reviewer and item,
  with a client submission UUID for idempotent retry. Corrections update only
  that reviewer’s row. Target-name reviews snapshot the database-derived name
  in `scientificName`.
- `list_review_batches`, `get_review_cursor`, and `save_image_review_v2` are the
  current browser-facing data operations. The original queue and submit RPCs
  remain temporarily available to authenticated deployed clients.

All exposed tables have RLS enabled and direct access is revoked from browser
roles. Functions derive the reviewer UUID from the authenticated JWT, use a
fixed safe search path, and return minimum shapes. Only the owning reviewer can
replace an answer through the version-checked RPC; review identity and rows
cannot be changed or deleted.

## Exact production setup order

1. Create or select a dedicated Supabase project.
2. Apply the migrations.
3. Enable anonymous Auth.
4. Set the GitHub repository variables.
5. Import a candidate campaign.
6. Deploy GitHub Pages.
7. Register, sign in, and review.

The following sections expand those steps. Never place administrative database
credentials or a server-side Supabase key in a `VITE_` variable.

### 1–2. Supabase project and migrations

Requirements are Node.js 24 LTS, npm, Docker for the local Supabase stack, and
the Supabase CLI supplied by the pinned npm lockfile.

```text
npm ci
npx supabase start
npx supabase db reset
npm run test:db
```

For the intended hosted project, authenticate the CLI, then:

```text
npx supabase link --project-ref "$SUPABASE_PROJECT_REF"
npx supabase db push
npx supabase db lint --linked --level warning
```

Inspect the target before pushing. The migration creates only the `private`
authorisation schema and the versioned VeriTaxa objects in `public`; it does not
drop unrelated tables. The database tests run in a transaction and verify
unauthenticated, inactive-profile, anonymous-registration, hidden-field,
versioning, non-deletion, and idempotency boundaries.

### 3. Configure name-only access

In Supabase Authentication > Sign In / Providers, enable anonymous sign-ins.
Email signup can remain disabled because VeriTaxa does not send authentication
emails or ask for an email or password.

The landing form asks only for a name. The frontend calls
`signInAnonymously()` with that name as display metadata; an Auth trigger stores
a private active profile, and the canonical review snapshot uses the profile
name. Supabase persists and refreshes the anonymous browser session so
returning users on the same browser remain signed in. The local equivalent is
recorded in `supabase/config.toml`.

The normal registration path requires no administrative provisioning. The
following optional legacy-support command can create or reactivate an
email-based reviewer profile when support intervention is needed.

Copy `.env.admin.example` to the ignored `.env.admin` and set:

```text
VERITAXA_DATABASE_URL=
SUPABASE_URL=
SUPABASE_SECRET_KEY=
```

These values are local admin credentials and must never be used by frontend
code or GitHub Pages. Supply the reviewer's email only at runtime:

```text
uv sync --frozen --group dev
uv run python -m tools.provision_reviewer \
  --email "$VERITAXA_REVIEWER_EMAIL" \
  --identified-by "$VERITAXA_IDENTIFIED_BY"
```

The command creates or finds the Supabase Auth user, activates the private
profile, and stores the nickname used by canonical exports as `identifiedBy`,
without printing the email or credentials.

### 4. Configure GitHub

Set public repository variables, not administrative secrets:

```text
gh variable set VITE_SUPABASE_URL --repo karikris/veritaxa
gh variable set VITE_SUPABASE_PUBLISHABLE_KEY --repo karikris/veritaxa
```

Enter the dedicated project's HTTPS URL and publishable browser key when
prompted. Do not use a server secret or service-role JWT. Enable Pages with
GitHub Actions as the source; `.github/workflows/pages.yml` deploys only after
the complete `CI` workflow succeeds on `main`.

### 5. Import a campaign

Candidate input may be Parquet, CSV, NDJSON, or JSONL. It requires `image_id`,
`image_url`, and `source_provider`; optional source columns are preserved, and
unrecognised pipeline columns are collected into `pipeline_metadata`. URLs must
be credential-free HTTPS URLs. Validate with a dry run first:

```text
uv run python -m tools.import_candidates \
  --input data/synthetic-candidates.ndjson \
  --campaign-code DEMO-001 \
  --internal-name "Synthetic smoke review" \
  --reviewer-name "Batch DEMO" \
  --batch-prefix DEMO \
  --target-scientific-name "Papilio exemplaris" \
  --batch-size 1000 \
  --status draft \
  --dry-run
```

Remove `--dry-run` only after inspecting the counts. Use `--status open` when
the campaign should immediately be reviewer-visible, or open the campaign and
batches administratively after validation. Input order is retained unless
`--shuffle-seed` is explicitly supplied. The importer never downloads images,
uses one publication transaction, caps logical batches at 1,000 rows, and omits
URLs and labels from normal logs. File reading, validation and duplicate checks
finish before database credentials are resolved. A private SQLite spool retains
validated records on disk; late validation or insertion failure cannot publish a
partial campaign. `--dry-run` never resolves database credentials or connects.

Insertion chunks are capped at 4 MiB without changing the requested logical
batch size or positions. A normalized candidate larger than 16 MiB is rejected;
a smaller candidate larger than the chunk budget is handled alone. These limits
are checked after decoding. CSV decoder buffers grow only for large records,
up to 64 MiB; NDJSON/JSONL encoded records are capped at 64 MiB. These exceptional
single-record cases have separate tests, not the normal 20 KiB-row memory guarantee.

CSV and NDJSON retain the original first-100-record type inference. Known field
types remain strict; changing a known field's type later may be rejected.
NDJSON fields first appearing after inference, including nested metadata keys,
are now preserved instead of silently discarded. Parquet retains its declared
schema. Unknown top-level values continue to override colliding metadata keys.

Shuffling uses the explicit `sha256-v1` global ordering algorithm; seed `0` now
shuffles normally. It is stable across input chunk sizes, but **does not reproduce
legacy Polars seed ordering**. The chosen algorithm and seed appear in the count
summary. See [the exact algorithm and end-to-end gates](benchmarks/README.md).

Pipelined inserts remain the default. COPY is exercised by the synthetic benchmark,
but it is not a general replacement for INSERT when row-level security applies;
no permissions or policies are weakened for a speed comparison.

### 6–7. Deploy and review

Merge a passing pull request into `main`. The Pages workflow builds with the
repository's public variables, scans source and `dist/` for private review
data, checks the compressed JavaScript budget, uploads only `dist/`, and
deploys to:

```text
https://karikris.github.io/veritaxa/
```

A reviewer can then enter their name, immediately choose an open neutral batch,
classify one image, and resume at the next unreviewed item later. Their session
and per-batch database progress are remembered on that browser.

Unsaved edits remain only in the current tab's memory; they are not database
reviews and do not survive reload or sign-out. Their retention is capped at 256
drafts and 1 MiB of serialized data. One slot and 16 KiB are reserved within those
limits for the active editor and its possible immutable retry request. At
capacity, navigation and batch changes pause until the reviewer saves or
explicitly discards the current local edits. Other drafts are not evicted.
An unresolved save cannot be discarded: retry its original request first,
because a failed browser response does not prove the database write failed.

Review images use a distinct supplied `display_url`, or an already display-sized
Flickr rendition. A preview failure does not automatically download an
uncontrolled original. **Inspect source image** loads the supplied source URL on
request, replacing the preview; **Return to preview** releases it. Each new item
starts in preview mode. The source URL can itself be a rendition, so this button
does not promise a higher-resolution file than the upstream data provides.

Prepare display URLs upstream with a longest edge of at most 1,600 pixels. For
Flickr, select a permitted size from [the sizes API](https://www.flickr.com/services/api/flickr.photos.getSizes.html):
its [URL rules](https://www.flickr.com/services/api/misc.urls.html) assign separate
secrets to each size at or above 1,600 pixels and to originals. VeriTaxa never
guesses a new secret or rewrites those URLs. Existing supplied small renditions
remain usable, including documented legacy farm hosts; duplicated unknown URLs
require explicit source inspection. No image mirror or live data rewrite is added.

An oversized supplied preview is released when its decoded dimensions become
known. This is a post-load guard, not a hard bound on the initial decoder
allocation or on explicitly requested source images. Supply genuine smaller
renditions rather than relying on CSS scaling to save image memory.

## Local frontend development

Copy `.env.example` to `.env.local`, replace its two public placeholders, then:

```text
npm ci
npm run dev
```

The production-equivalent checks are:

```text
npm run lint
npm run format:check
npm run check
npm test
npm run test:e2e
npm run build
npm run data:check
npm run bundle:check
uv sync --frozen --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
git diff --check
```

Browser tests use only fictional metadata and intercepted synthetic SVG
responses; they do not require a real image host or task database.

## Export reviews

Export a canonical joined dataset as Parquet or CSV:

```text
uv run python -m tools.export_reviews \
  --campaign-code DEMO-001 \
  --output reviewed/demo-reviews.parquet
```

The default export retains source metadata, the campaign target, the granular
human label, selected `scientificName`, legacy `flickrKeyword` when present,
comment, reviewer UUID, `identifiedBy`, most recent answer time, schema
version, and client version. `--derived` adds pipeline group columns while
preserving the canonical label.

Use `--lean` to omit only `source_labels` and `pipeline_metadata` from either
export. This opt-in projection removes those fields in SQL before decoding;
the default full export continues to retain provenance.

Use `--consensus` for one row per reviewed image:

```text
uv run python -m tools.export_reviews \
  --campaign-code DEMO-001 \
  --output reviewed/demo-consensus.csv \
  --consensus
```

Consensus rows contain the plurality label, review count, unanimity and tie
flags, and latest correction time. Ties use the canonical expected-result
priority while remaining marked as tied. Reviewer identity and comments stay
exclusive to the default individual export.

With `--derived`, tied consensus is always marked
`excluded_from_automatic_training`, even if the priority winner is a positive
label. Raw rows retain batch/item position, then review creation/ID order;
consensus rows sort lexically by campaign code, batch code and image ID.

Exports stream through one read-only, repeatable-read database snapshot. Keep
the admin connection available until completion; long exports retain that
snapshot while writing. CSV retains one row; Parquet writes batches of at most
1,000 rows or 4 MiB of field payload. A single row above that batch budget is
written alone, up to a 16 MiB UTF-8 field-payload limit. Larger rows fail; this
limit is checked after database decoding and is not a bound on arbitrary JSON
decoder allocations. Full and lean exports never silently truncate fields.
Each completed file is staged privately alongside its destination and atomically
replaces it only after success. Interrupted exports leave any previous completed
file intact. See [synthetic end-to-end memory gates](benchmarks/README.md).

## Dependencies

The only runtime package is the pinned Supabase JavaScript client, required for
Auth and typed RPC transport. Vite and TypeScript build the framework-free
frontend; Vitest and Playwright cover domain, state, browser, keyboard, and
responsive behaviour. The pinned Supabase CLI runs local migration tests.
Polars provides import and small-frame compatibility operations; Psycopg provides
transactional writes and incremental database reads. PyArrow writes bounded
Parquet batches and is not loaded for CSV exports. pytest and Ruff test and check
the Python tools. Exact JavaScript and Python resolutions are committed in
`package-lock.json` and `uv.lock`.

## Known limitations

- Version 3 records one current label per reviewer and item. Consensus is an
  export view rather than a stored adjudication.
- `identifiedBy` records the broad-image classifier's nickname; it does not
  turn the response into a taxonomic identification or species confirmation.
- Labels describe the whole visible image; positive detector training still
  requires boxes, masks, accepted pseudo-localisation, or another localisation
  process.
- Source-host availability, hotlink policy, and bandwidth are external to
  VeriTaxa. A failed display URL is tried once with its fallback, then the human
  reviewer decides whether to use `image_unavailable`.
- GitHub Pages and Supabase do not proxy or cache source image bytes.
- A name-only session cannot be recovered after sign-out, browser-data
  deletion, or moving to another device.
- Anonymous Auth creation is rate-limited and should be protected with CAPTCHA
  before advertising the site to an untrusted high-volume audience.
- Production deployment intentionally fails if either public Supabase variable
  is absent or resembles a server credential.

No real candidate data, reviewer emails, source URLs, model outputs, exports,
or administrative credentials belong in this repository. The CI data-leak scan
enforces common accidental-disclosure patterns.

## Licence

VeriTaxa is licensed under the GNU Affero General Public License v3.0. See
[LICENSE](LICENSE).
