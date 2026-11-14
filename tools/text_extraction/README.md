# Text extraction library

Local tools for extracting reviewable geographic and temporal clues from Flickr
exports. The library reads saved metadata, comments and provider responses. It
does not call Flickr, upload image text, install an NLP model, publish reviews or
assign inferred coordinates to a target image.

## Run

Use the repository's existing Python environment and Polars dependency:

```bash
uv run python -m tools.text_extraction.exploration.fetch_gazetteer \
  --output /private/analysis/gazetteer

uv run python -m tools.analyse_flickr_geolocation \
  --source /private/analysis/original.parquet \
  --geotagged-source /private/analysis/geotagged.parquet \
  --cache /private/analysis/flickr_cache.sqlite \
  --gazetteer /private/analysis/gazetteer \
  --output /private/analysis/location_clues

uv run python -m tools.text_extraction.exploration.validate_outputs \
  --analysis /private/analysis/location_clues
```

The gazetteer downloader uses public GeoNames files under CC BY 4.0. Existing
files are reused and checksummed. The analysis itself has no network dependency.
Keep downloaded gazetteers, source snapshots, image URLs, comments and exports
outside Git. The pipeline refuses a changed source snapshot in an existing run
directory; use a new directory for newer metadata or reviews.

## Python interfaces

```python
from pathlib import Path

from tools.text_extraction import (
    Gazetteer,
    coordinate_tags,
    evidence_for_unit,
    relative_clues,
    temporal_neighbors,
    text_coordinates,
    visible,
)

text, links = visible("Photographed at <b>Paris, France</b>.")
places = Gazetteer(Path("/private/analysis/gazetteer"))
unit = {"source": "description", "text": text, "author_is_owner": True}
clues = evidence_for_unit(unit, places, set())
```

All matches are candidate evidence. Gazetteer settlement coordinates describe
named features, map coordinates may be map centers, and temporal coordinates
belong to the reference image. None is silently copied into the target's inferred
latitude or longitude. Owner-profile locations describe the account holder.
Context rules are heuristics, with an intentionally reviewable long-form output.

## Modules

| Module        | Responsibility                                                                                                        |
| ------------- | --------------------------------------------------------------------------------------------------------------------- |
| `html_text`   | Visible HTML text and separately retained links; excludes image alt text and scripts                                  |
| `coordinates` | Provider-compatible coordinate checks, raw machine tags, labelled decimal, hemisphere, DMS and numeric map links      |
| `gazetteer`   | Unicode token matching against countries, regions and settlements; preserves alternatives                             |
| `context`     | Capture clauses, country context, owner/commenter distinction, questions, distribution, greetings and relative timing |
| `temporal`    | Same-owner recorded capture-time neighbors, with direction and a stated timezone limitation                           |
| `flickr`      | Saved-export adapters and read-only SQLite provider-location extraction                                               |
| `evidence`    | Stable identities, duplicate occurrence counts, schemas and empty-result handling                                     |
| `pipeline`    | Frozen inputs, joins, exports, source/code/gazetteer fingerprints                                                     |

The runtime uses the repository's existing Polars dependency. It does not require
spaCy, Mordecai, Elasticsearch or a geocoding service. English
context rules and a limited gazetteer cannot recover every language, landmark,
historical place name or indirect reference.

## Exploration scripts retained from this investigation

Run each with `python -m tools.text_extraction.exploration.<name> --help`.

| Script                   | Inputs                                      | Investigation reproduced                                                                                              |
| ------------------------ | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `profile_cache`          | `--source`, optional `--cache`              | Grain, columns, capture precision, comment authors, text coverage, cache states and optional-tool availability        |
| `fetch_gazetteer`        | `--output`                                  | Exact public gazetteer inputs, file sizes and hashes                                                                  |
| `inspect_candidates`     | `--analysis`, optional `--sample`, `--seed` | Frequent raw/eligible matches, deterministic text samples and coordinate-method counts                                |
| `coordinate_tags`        | `--source`                                  | Raw versus normalized coordinates; decimal points and western/southern signs                                          |
| `inspect_temporal`       | `--analysis`                                | Earlier/later links, matching time windows, narrative types and one-hour expressions                                  |
| `validate_outputs`       | `--analysis`                                | Exact ID coverage, CSV/Parquet round trips, same-owner/time arithmetic, empty target coordinates and priority subsets |
| `archive.initial_screen` | Main pipeline arguments, optional `--limit` | Broad prototype retained to reproduce rejected filename, stopword and contextual matches                              |

The historical screen defaults to 1,000 source images and requires a fresh
output directory. `--limit 0` scans the complete source. Its outputs are
diagnostics; use the current pipeline for candidate extraction. See
[METHODS.md](METHODS.md) for measured results and limitations of every approach.

## Output contract

- `image_geolocation_clues.csv` / `.parquet`: exactly one row per original
  Flickr photo ID, with clue status, candidate feature JSON, provenance counts,
  temporal-anchor JSON and explicit unverified-location status.
- `location_evidence.csv` / `.parquet`: source field, comment identity and
  ownership where applicable, excerpt, place alternatives, flags, evidence ID
  and repeated occurrence count. Repeated identical evidence is collapsed;
  independent sources remain distinct.
- `relative_time_evidence.csv` / `.parquet`: original expression, parsed time
  quantity, direction, context, narrative type and unresolved reference basis.
- `temporal_geotagged_neighbors.csv` / `.parquet`: target/reference photo IDs,
  capture times, titles, reference coordinates and signed minutes before target.
  Positive minutes mean earlier; negative minutes mean later. The closest
  reference per direction/window is retained alongside the number of matches.
- Input snapshots, projected provider responses and `analysis_manifest.json`:
  checksums and the exact extraction rules' code fingerprints.

Validation also writes `priority_location_clues.csv`, `hour_before_neighbors.csv`,
`hour_after_neighbors.csv` and `validation_receipt.json`. These are review aids;
the categories overlap. Unknown/coarse capture dates, midnight placeholders and
incompatible timezone representations cannot support hourly matching. No travel
speed, uncertainty radius or interpolated target coordinate is assumed.

## Four-tab human-classification workbook

```bash
uv run python -m tools.export_geolocation_review_workbook \
  --source /private/analysis/original.parquet \
  --clues /private/analysis/location_clues/image_geolocation_clues.parquet \
  --output /private/analysis/target_location_review.xlsx
```

The workbook selects images with at least one saved human target classification.
`--target` defaults to `Papilio demoleus`; `--round` defaults to `first_round`
and can select `second_round`. Conflicting classifications remain flagged in the
original review columns. The four worksheets are disjoint and ordered: priority
location clues, other location hints, profile-only hints, no supported hints.
All source metadata is preserved, duplicate context aliases are excluded, and
reviewer-name fields support filtering across accounts with the same name.
Every exported value is checked against a private CSV snapshot. Long text uses
continuation columns, URLs are clickable, and formulas are never inferred from
source text. A JSON receipt records source hashes, counts and the validation.

## Attach and group saved clues on live images

`tools.location_clue_groups.build_payload` combines an image's summary, full
location evidence, relative-time evidence and temporal references. It assigns one
primary group and retains all applicable source/type tags. Coordinate references,
named locality candidates and nearby geotagged photos take precedence; remaining
groups distinguish owner comments, photo text, other comments and relative timing.
Profile locations, greetings, species ranges and questions do not independently
qualify an image for these groups. All supporting evidence and its flags remain
available in the private payload.

Prepare a private gzip JSONL plan with `item_id`, `source_provider`,
`source_record_id` and `payload` per image, then validate it against live records:

```text
uv run python -m tools.attach_location_clues \
  --env-file /secure/config.env --plan /private/attachment-plan.jsonl.gz \
  --output /private/location-attachment
```

Add `--publish` to attach each payload under
`pipeline_metadata._veritaxa_location_clues`. Each update compares the complete
previous metadata value, retries concurrent metadata changes using a fresh read,
and verifies the returned merged value. Matching existing payloads are skipped.
The output directory retains the initial metadata backup and per-item results for
recovery and resuming partial runs. Plans and backups must stay outside Git.

Clues retain source hashes and unverified status. Target latitude and longitude
remain empty: named-place centers, quoted coordinates, profile locations and
reference-photo coordinates are never promoted to the target's capture location.
The enrichment remains private administrative metadata and is not added to the
reviewer RPCs. Dataset membership, image IDs, existing model metadata and saved
human classifications are preserved.

## Checks

```bash
uv run pytest tools/tests/test_analyse_flickr_geolocation.py
uv run pytest tools/tests
uv run ruff check tools/text_extraction tools/analyse_flickr_geolocation.py \
  tools/tests/test_analyse_flickr_geolocation.py
node scripts/check-no-review-data.mjs
git diff --check
```

Tests use synthetic photo records, local SQLite fixtures and a tiny synthetic
gazetteer. They make no provider calls and require no real Flickr data.
