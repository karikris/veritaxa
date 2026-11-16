# Private photo map

A separate Streamlit viewer for a versioned review snapshot. The review website
keeps its existing one-page application and review controls.

The world map groups photographs into 10,000 m grid cells in EPSG:6933 and plots
the cell centres. Marker area grows with the image count, capped for readability.
Colour follows the most recent reliable photo date in each cell, using a fixed
blue-to-red scale across date filters. Capture dates take priority over upload
dates; month/year precision is preserved and invalid/future capture dates use the
upload date. Display binning does not improve the source coordinate accuracy.

Hover to load a thumbnail. Click or tap to pin the card; previous/next controls
browse photographs sharing a cell. **Cards show only the photograph and date.**
Source image identifiers, source URLs, original coordinates and location provenance are
not sent in the map payload. Thumbnails are downloaded by the server, resized,
stripped of source metadata, and returned through the authenticated app session.
The private snapshot retains coordinate provenance.

Each photo has an **Include in CSV** checkbox. Deselection persists through map
navigation and date filters for the signed-in session. Excluded photos remain
available for re-selection; **Include all visible** restores the current date
range. Marker counts, sizes and colours follow the included observations.

**Download CSV** exports exactly the selected observations in the current date
range, with four columns: `image_url`, `date`, `geotag`, `bioclip_label`. Dates are
ISO formatted with their original day/month/year precision. Geotags are the same
10 km cell centres used on the map. The label is the actual BioCLIP top-1 label,
or blank when unavailable. Source URLs and model labels are sent to the viewer
only in an explicitly requested CSV. An explicit click-time key list prevents an
export racing the server's selection acknowledgement. Selections are temporary;
the app does not alter review records.

## Local preview

Use Python 3.12 or newer. From the repository root:

```bash
uv venv --python 3.12 .venv-map
uv pip install --python .venv-map/bin/python -r apps/review_map/requirements.txt
.venv-map/bin/streamlit run apps/review_map/app.py
```

Configure `.streamlit/secrets.toml` (ignored by Git):

```toml
MAP_SNAPSHOT_PATH = "/absolute/path/to/private-snapshot.json"
MAP_ACCESS_PASSWORD_SHA256 = "sha256-of-a-strong-viewer-password"
```

Generate the viewer password outside Git and store only its SHA-256 in the app
settings. Without an access secret, the app stops before loading private data.
`MAP_CACHE_DIR` optionally chooses a private thumbnail-cache directory; the default
is an app-owned temporary directory. Downloads are bounded to 8 MiB and a fixed
source-host allowlist, including each redirect. Thumbnails expire after 24 hours;
the disk cache is capped at 1,024 entries.

## Prepare and publish a snapshot

The administration environment supplies the existing approved Supabase connection
and cached Flickr metadata. The campaign is runtime configuration, not a hardcoded
taxon or review-task identifier:

```bash
.venv/bin/python -m tools.prepare_review_map \
  --campaign-code "$MAP_CAMPAIGN_CODE" \
  --env-file "$ADMIN_ENV_FILE" \
  --flickr-cache "$FLICKR_INFO_CACHE" \
  --title "$MAP_TITLE" \
  --expected-count "$MAP_IMAGE_COUNT" \
  --output "$PRIVATE_SNAPSHOT_FILE"

.venv/bin/python -m tools.publish_review_map \
  --snapshot "$PRIVATE_SNAPSHOT_FILE" \
  --env-file "$ADMIN_ENV_FILE" \
  --private-output "$PRIVATE_STORAGE_RECEIPT"
```

Both outputs contain private material and must stay outside Git. The publisher
uses a **private** Storage bucket, content-addressed object names, verifies the
download checksum, and writes its signed download URL to the private receipt.
The URL grants read access only to that snapshot and expires after one year by
default. Refresh it before expiry. No Supabase administrative key is needed by the
viewer app.

## Streamlit Community Cloud

Create an app from the repository's `main` branch with entrypoint
`apps/review_map/app.py`, choose Python 3.12, and enter the desired subdomain in the
App URL field. Community Cloud confirms whether the name is available; an
anonymous not-found/no-access page is not proof that a name can be reserved.

Copy the settings in `secrets.toml.example` into the Cloud Secrets editor. Set
`MAP_SNAPSHOT_URL` to the signed private snapshot URL and
`MAP_ACCESS_PASSWORD_SHA256` to the viewer-password hash. Do not copy local
`MAP_SNAPSHOT_PATH` or local cache paths into Cloud. Keep the signed URL and viewer
password separate from the public code and deployment links. The entrypoint's
pinned requirements file supplies the Cloud dependencies.

## Checks

```bash
uv pip install --python .venv-map/bin/python pytest==9.1.1
.venv-map/bin/python -m pytest -q apps/review_map/tests
node --check apps/review_map/frontend/map.js
npm run data:check
git diff --check
```

Tests use synthetic records and images, never live review data or real model
weights. Browser verification also checks image loading on hover, carousel
navigation, preserved map position, mobile tap behaviour, unavailable images and
absence of private source references in map/hover payloads. Selection tests check
date filtering, exact CSV fields, excluded observations and preserved date precision.

Leaflet 1.9.4 is vendored under its BSD-2-Clause licence in
`frontend/vendor/LICENSE`; only CSS line endings and trailing whitespace are normalized.
Basemap attribution remains visible on the map.
