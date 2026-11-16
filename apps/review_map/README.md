# Photo map

A separate Streamlit viewer for a versioned review snapshot. The review website
keeps its existing one-page application and review controls. The map opens
directly for all visitors and requires no viewer password.

The world map groups photographs into 10,000 m grid cells in EPSG:6933 and plots
the cell centres. Marker area and count labels use distinct date/location series,
capped for readability. All photos on the same calendar day in the same 10 km
cell contribute one series; different dates count separately. Missing dates and
month/year-only dates stay separate because a shared day cannot be established.
CSV exports and the photo carousel retain every image.
Colour follows the most recent reliable photo date in each cell, using a fixed
blue-to-red scale from 2004 to 2026 across date filters. The date slider covers
2004-2026 and initially selects that entire period. Earlier dates stay blue;
2026 and later dates stay red. The initial world view is the furthest zoom-out
level; wheel, pinch, keyboard and zoom controls can zoom in and back to that view.
Wheel/trackpad zoom uses quarter-level steps, a short debounce and immediate
updates to avoid sluggish animated scrolling.
The minimum zoom also fills the viewport on wide displays. Dragging is bounded to
a single world extent; repeated world tiles and pinch zoom bounce are disabled.
Capture dates take priority over upload
dates; month/year precision is preserved and invalid/future capture dates use the
upload date. Display binning does not improve the source coordinate accuracy.

Hover to load a thumbnail. Click or tap to pin the card; previous/next controls
browse photographs sharing a cell. **Cards show the photograph, date and its BioCLIP top-1 label.**
Source image identifiers, source URLs, original coordinates and location provenance are
not sent in the map payload. Thumbnails are downloaded by the server, resized,
stripped of source metadata, and returned through the app session.
The private snapshot retains coordinate provenance.

The card's **Exclude this image** checkbox affects the currently displayed image
only. Its status states whether that image is included, excluded manually, or
excluded by a specific continent/model filter. Restoring an image individually
can override an active filter without restoring its neighbours. The separate
**Exclude this location** checkbox still applies to every image at that 10 km
location, including dates outside the current map filter.

A top-1 label filter acts on each image's own label. A mixed-label bubble retains
its matching included images and shrinks only as their series are excluded. The
included bubble opens on an included image; the small grey square opens an
excluded image. The carousel keeps all images available, with an independent
checkbox and status for each. A partly excluded location has a mixed-state
location checkbox and an excluded/total count. **Clear exclusions** clears manual
exclusions, individual inclusion overrides and both dropdown filters.

The **Continents** multiselect dropdown beside **Include all visible** starts
with every continent selected. Deselect a continent to exclude all its images;
select it again to restore them. The filter applies to all dates, with Africa
split into **North Africa** and **Sub-Saharan Africa**. Region filters and manual
location exclusions are independent: clearing a continent exclusion preserves
manual location and image exclusions. **Include all visible** restores images
within the map's current date range while preserving exclusions outside it and
keeping the dropdown choices. **Clear exclusions**
restores all images. Geographic
lookup runs offline using bundled [public boundaries](geography/README.md).

The **BioCLIP top-1** multiselect lists every distinct top-1 label from the snapshot
with its image count. Labels start selected; deselect labels to exclude them from
the map selection and CSV. Both dropdowns offer **Select all** and **Clear selection**;
the label dropdown also supports search. To keep one species, clear its selection
and tick that label. These filters combine with continent and location exclusions.

**Download CSV** includes every image by default, across all dates. The optional
**Apply date filter to CSV** checkbox limits the export to the dates shown on the
map. Location and continent exclusions apply in either mode and persist across
map navigation and date changes for the browser session. Exports have four
columns: `image_url`, `date`, `geotag`, `bioclip_label`. Dates preserve their original
day/month/year precision. Geotags are the same 10 km cell centres used on the map.
The label is the actual BioCLIP top-1 label, or blank when unavailable. Model labels
are available in the filter controls; source URLs reach the viewer only in an
explicitly requested CSV. An explicit
click-time key list prevents an export racing a selection acknowledgement.
Selections are temporary; the app does not alter review records.

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
```

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
`MAP_SNAPSHOT_URL` to the signed private snapshot URL. Do not copy local
`MAP_SNAPSHOT_PATH` or local cache paths into Cloud. Keep the signed URL separate
from the public code and deployment links. Set the Cloud app's sharing access to
public so everyone can open it. The entrypoint's pinned requirements file supplies
the Cloud dependencies. The component cache is keyed by the HTML, CSS and JavaScript
contents, so frontend-only changes take effect without reusing an older renderer.

## Checks

```bash
uv pip install --python .venv-map/bin/python pytest==9.1.1
.venv-map/bin/python -m pytest -q apps/review_map/tests
node --check apps/review_map/frontend/map.js
node --test apps/review_map/tests/selection.test.mjs
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
