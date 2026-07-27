# VeriTaxa

VeriTaxa is a minimal, authenticated, one-page tool for recording broad human
labels against image candidates collected by BioMiner and related pipelines.
It shows one image at a time, saves one classification and an optional comment,
then advances only after Postgres confirms the write.

VeriTaxa is separate from ButterflyLens. ButterflyLens remains the
Australia-focused evidence and species-verification application; VeriTaxa is a
taxon-independent bulk image-triage tool.

Image-level labels describe what is visibly present. They are not bounding
boxes, segmentation masks, detector-ready localisation annotations,
species-level confirmations, or verified occurrence records.

## Architecture and privacy boundary

GitHub Pages hosts only the compiled static interface. Supabase stores private
campaigns, batches, source image URLs, hidden source metadata, the reviewer
allowlist, and append-only reviews. Authentication, the private allowlist,
row-level security, and narrowly scoped security-definer RPC functions prevent
anonymous or unapproved users from receiving task URLs or progress.

The browser uses a normal `<img>` element to download the displayed image
directly from its source host. There is no iframe, server image proxy, image
mirror, Supabase image transfer, or application-owned image store. Only the
current image and, after it loads, at most one next image are requested. Data
saver mode disables prefetch.

Reviewer RPC responses contain only neutral batch details, progress, item IDs,
and display/fallback URLs. Scientific targets, search terms, source labels,
titles, tags, model outputs, confidence values, and previous reviews remain in
Postgres and never enter reviewer-facing responses or the DOM.

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

The stored schema version is `veritaxa-review-label-v1`. The granular code is
canonical; display labels and derived training groups are not stored as
redundant review columns.

| Stored code                | Display label                   |
| -------------------------- | ------------------------------- |
| `adult_butterfly`          | Adult butterfly                 |
| `caterpillar`              | Caterpillar                     |
| `moth`                     | Moth                            |
| `other_insect`             | Other insect                    |
| `arachnid`                 | Spider or other arachnid        |
| `other_arthropod`          | Other arthropod                 |
| `plant`                    | Plant                           |
| `mammal_or_person`         | Mammal or person                |
| `bird`                     | Bird                            |
| `other_animal`             | Other animal                    |
| `fungus`                   | Fungus                          |
| `artifact_or_illustration` | Object, artwork or illustration |
| `no_biological_subject`    | No clear biological subject     |
| `uncertain`                | Uncertain                       |
| `image_unavailable`        | Image unavailable               |

For images with several subjects, choose the most pipeline-relevant visible
subject in the order above, except animals take priority over plants and fungi:
adult butterfly, caterpillar, moth, other insect, arachnid, other arthropod,
mammal or person, bird, other animal, plant, fungus, artifact, no clear
biological subject, uncertain, then unavailable. A real pinned butterfly is an
adult butterfly; a butterfly drawing, logo, toy, tattoo, or screenshot is an
artifact.

The versioned definitions and pipeline mappings are in
`src/domain/reviewLabels.ts` and `schemas/review-labels-v1.json`.

## Database model and access

- `private.reviewer_allowlist` adds application authorisation to Supabase Auth.
- Each allowlist row assigns a required reviewer nickname. Reviews snapshot it
  in the requested dataset field `identifiedBy`.
- `review_campaigns` retains internal scientific and source context.
- `review_batches` divides campaigns into neutral batches of at most 1,000
  items.
- `review_items` stores image URLs and hidden source/pipeline metadata.
- `image_reviews` stores one append-only response per reviewer and item, with a
  client submission UUID for idempotent retry.
- `list_review_batches`, `get_review_queue`, and `submit_image_review` are the
  only browser-facing data operations.

All exposed tables have RLS enabled and direct access is revoked from browser
roles. Functions derive the reviewer UUID and email from the authenticated JWT,
use a fixed safe search path, and return minimum shapes. Reviews cannot be
edited or deleted through the reviewer application.

## Exact production setup order

1. Create or select a dedicated Supabase project.
2. Apply the migrations.
3. Provision a reviewer.
4. Configure Auth site and redirect URLs.
5. Set the GitHub repository variables.
6. Import a candidate campaign.
7. Deploy GitHub Pages.
8. Sign in and review.

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
anonymous, unauthorised, allowlisted, hidden-field, append-only, and idempotency
boundaries.

### 3. Provision a reviewer

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
allowlist row, and stores the nickname used by canonical exports as
`identifiedBy`, without printing the email or credentials. If Auth
administration is unavailable, it gives the exact Authentication > Users
dashboard action and leaves the allowlist update explicit.

### 4. Configure Auth URLs

In Supabase Authentication URL configuration, set:

```text
Site URL: https://karikris.github.io/veritaxa/
Redirect URL: https://karikris.github.io/veritaxa/
```

Keep public email signup and anonymous sign-in disabled. The frontend requests
email magic links with `shouldCreateUser: false`, so only a pre-provisioned Auth
user who is also active in the private allowlist can access tasks. The local
equivalents are recorded in `supabase/config.toml`.

### 5. Configure GitHub

Set public repository variables, not administrative secrets:

```text
gh variable set VITE_SUPABASE_URL --repo karikris/veritaxa
gh variable set VITE_SUPABASE_PUBLISHABLE_KEY --repo karikris/veritaxa
```

Enter the dedicated project's HTTPS URL and publishable browser key when
prompted. Do not use a server secret or service-role JWT. Enable Pages with
GitHub Actions as the source; `.github/workflows/pages.yml` deploys only after
the complete `CI` workflow succeeds on `main`.

### 6. Import a campaign

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
  --batch-size 1000 \
  --status draft \
  --dry-run
```

Remove `--dry-run` only after inspecting the counts. Use `--status open` when
the campaign should immediately be reviewer-visible, or open the campaign and
batches administratively after validation. Input order is retained unless
`--shuffle-seed` is explicitly supplied. The importer never downloads images,
uses a transaction, splits batches at 1,000 rows, and omits URLs and labels from
normal logs.

### 7–8. Deploy and review

Merge a passing pull request into `main`. The Pages workflow builds with the
repository's public variables, scans source and `dist/` for private review
data, checks the compressed JavaScript budget, uploads only `dist/`, and
deploys to:

```text
https://karikris.github.io/veritaxa/
```

An approved reviewer can then request a magic link, choose an open neutral
batch, classify one image, and resume at the next unreviewed item later.

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

The export retains source metadata, the granular human label, comment, reviewer
UUID, `identifiedBy`, review time, schema version, and client version.
`--derived` adds pipeline group columns while preserving the canonical label.

## Dependencies

The only runtime package is the pinned Supabase JavaScript client, required for
Auth and typed RPC transport. Vite and TypeScript build the framework-free
frontend; Vitest and Playwright cover domain, state, browser, keyboard, and
responsive behaviour. The pinned Supabase CLI runs local migration tests.
Polars provides streaming-friendly tabular import/export, Psycopg provides
transactional admin writes, and pytest plus Ruff test and check the Python
tools. Exact JavaScript and Python resolutions are committed in
`package-lock.json` and `uv.lock`.

## Known limitations

- Version 1 records one label per reviewer and item, with no editing,
  adjudication, consensus, or public registration.
- `identifiedBy` records the broad-image classifier's nickname; it does not
  turn the response into a taxonomic identification or species confirmation.
- Labels describe the whole visible image; positive detector training still
  requires boxes, masks, accepted pseudo-localisation, or another localisation
  process.
- Source-host availability, hotlink policy, and bandwidth are external to
  VeriTaxa. A failed display URL is tried once with its fallback, then the human
  reviewer decides whether to use `image_unavailable`.
- GitHub Pages and Supabase do not proxy or cache source image bytes.
- Magic-link delivery depends on the hosted project's email configuration and
  rate limits.
- Production deployment intentionally fails if either public Supabase variable
  is absent or resembles a server credential.

No real candidate data, reviewer emails, source URLs, model outputs, exports,
or administrative credentials belong in this repository. The CI data-leak scan
enforces common accidental-disclosure patterns.

## Licence

VeriTaxa is licensed under the GNU Affero General Public License v3.0. See
[LICENSE](LICENSE).
