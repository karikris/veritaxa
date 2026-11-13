# Flickr location extraction: methods and findings

This documents the explicitly requested investigation of the historical
18,041-image collection, using the completed metadata/comment cache on
12 November 2026. It is candidate discovery, not an occurrence-release process.
There were **103,854 comment records** available. The investigation made **zero
new Flickr API calls** and did not modify saved human classifications or the
website. Real source rows, excerpts, URLs and exports remain in ignored local
analysis storage; this public-code report contains aggregate findings only.

## Approaches actually executed

Counts below describe automatically extracted evidence and overlap across rows.
They are not counts of validated photograph locations.

| Approach                                                             |                                              Result in this pass | Interpretation and limits                                                                                                                                                                       |
| -------------------------------------------------------------------- | ---------------------------------------------------------------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Read `getInfo.photo.location` directly from saved provider responses |                                                         2 images | Public source coordinates were available even though the earlier joined export had not populated them. Retained as provider assertions.                                                         |
| Read raw latitude/longitude machine tags                             |                                                          1 image | Flickr's normalized tag content had removed decimal points and the minus sign. The raw tag retained the pair. No scaling of normalized integers was attempted.                                  |
| Labelled decimal coordinates in visible text                         |                                                         0 images | Supported syntax was scanned; absence here is not proof that other unrecognized formats are absent.                                                                                             |
| Decimal coordinates with hemisphere letters                          |                                                         0 images | Separate parser supports signed hemispheres and range checks.                                                                                                                                   |
| Degrees/minutes/seconds in descriptions/comments                     |                                                         7 images | One image has an explicit locality/coordinate caption. Six quote coordinates of the same named mountain feature; those can describe the feature rather than the camera position.                |
| Numeric map links in saved HTML links                                |                                                         0 images | Tested numeric query parameters, map centers and latitude/longitude paths. Short links were not expanded and map services were not queried.                                                     |
| Countries, regions and settlements in titles, descriptions and tags  | 3,641 images with at least one eligible named-locality candidate | These remain unvalidated candidates. Country-only matches are coarse; place aliases and ambiguous cities retain alternatives.                                                                   |
| Place mentions in photo-owner comments                               |                                                       640 images | Raw source-aware screening count, including mentions that are not capture assertions. Context flags retain distribution, questions and greetings.                                               |
| Place mentions in third-party comments                               |                                                     2,508 images | May identify the commenter, a species range or a question; not automatically treated as the photo's location.                                                                                   |
| Relative-time and clock expressions                                  |                                                       315 images | Includes 168 images with travel/itinerary timing, 171 with explicit clock text, and 13 with biological-stage timing. These subsets overlap. Hatching/emergence timing is not a location offset. |
| Same-owner geotagged reference within one recorded hour              |                                                       181 images | 82 have an earlier reference; 131 have a later reference. Earlier/later subsets overlap and same-time references are separately represented.                                                    |
| Same-owner geotagged reference within 24 recorded hours              |                                                       283 images | Includes the one-hour subset. Only supplied cached collections were searched.                                                                                                                   |
| Owner-profile locality                                               |    2,164 images have this as their only geographic clue category | The account holder's profile location is not the photograph location. It is retained separately.                                                                                                |

The priority review file contains **3,807 unique images** with a public coordinate,
raw coordinate pair, text coordinate reference, eligible named locality or
one-hour reference. The full image table retains all 18,041 IDs exactly once.
There are **172,712 unique location-evidence rows** and **394 selected temporal
links**. A further 1,246 duplicate occurrences of identical source evidence are
counted in `occurrence_count`. All inferred target-coordinate fields remain
empty pending review.

## Broad screen and corrections

The initial broad GeoNames screen generated **401,137 evidence rows** and
proposed **8,951 candidate images**. Inspection exposed camera filenames such as
`IMG`/`DSC`, ordinary words such as `and`, and generic park/group language matched
to geographic aliases. That first result was rejected as a priority count.
The preserved historical script reproduces the broad matcher for diagnostic use.

The current extraction adds minimum alias lengths, common-word and photography
filters, source ownership, capture-clause checks, biological-distribution and
group/greeting flags, canonical-versus-alternate names and country context.
Country/city homonyms can use other geographic evidence; an ambiguous name does
not confirm its own country. The resulting 3,641 is a different screening-rule
count, **not an accuracy estimate**. Residual ambiguous or irrelevant matches
remain possible and are visible in the long-form evidence table.
Common-word filters can also suppress genuine place names. This screen does not
establish exhaustive geographic coverage or the absence of other location clues.

The raw-coordinate diagnostic also exposed a distinct normalization failure:
normalized machine-tag strings and raw API strings could disagree because
punctuation was removed. The parser now prefers raw tag values, checks ranges,
keeps signs, and refuses conflicting valid pairs.

## Temporal interpretation

The timestamp comparison uses Flickr account IDs and recorded capture times,
not upload dates or comment-posting times. Unknown/coarse dates, midnight
placeholders and incompatible timezone representations are excluded. Each link
retains both source IDs, the direction, exact time difference, source coordinates
and source text. The recorded times do not establish a verified timezone.

A reference photographed an hour earlier can prioritize location review. It
does not establish that the target was photographed at that point. The tools
do not assume a travel speed, interpolate a location or manufacture an
uncertainty radius. Narrative phrases such as "an hour earlier" also retain an
unresolved reference: they may refer to a trip, a comment or an organism's age.

## Data and extraction controls

HTML is reduced to visible text; links are retained separately. Image alt text,
scripts, group badges and owner-profile fields are not silently merged into
capture evidence. Current and discovery text versions are preserved when they
differ. Comment records retain their original identifiers and owner/nonowner
attribution. Stable evidence identities collapse repeated identical excerpts
while retaining repeat counts.

The actual input Parquet snapshots, projected cache-location responses and
GeoNames downloads are checksum-bound. Validation checked every source ID,
CSV/Parquet agreement, uniqueness of evidence identities, all same-owner links,
all time differences/directions, exclusion of self-reference photos and empty
inferred coordinates. The library supports typed empty-result exports.

## Considered or unavailable, and not executed

- spaCy/Mordecai contextual geoparsing: inspected upstream source and checked
  runtime availability. The required NLP models/search infrastructure were not
  installed; no neural geoparser or Elasticsearch query ran.
- Geocoding services and new Flickr owner-photostream searches: not invoked.
  Coverage is limited to the saved original and geotagged collections.
- Timezone recovery, camera-clock correction, travel-speed estimation and
  numeric spatial uncertainty: not inferred from the available evidence.
- OCR, pixel-based landmark recognition and new EXIF extraction: not run in
  this text-analysis pass. Prior BioCLIP category scores were not used as
  geographic evidence.
- Human adjudication of all candidate locations: not performed. No biological
  occurrence or verified-coordinate count is claimed.

## Source and method references

- [GeoNames dump format and attribution](https://download.geonames.org/export/dump/readme.txt):
  the downloaded countries, first-level regions and cities1000 files are CC BY
  4.0. The snapshot contained 175,955 indexed features. Landmarks and smaller
  settlements can be absent; alias matching is not contextual geoparsing.
- [Flickr getInfo documentation](https://www.flickr.com/services/api/flickr.photos.getInfo.html):
  source text, raw tags, owner identity and capture-date fields were inspected.
- [GBIF Georeferencing Best Practices](https://docs.gbif.org/georeferencing-best-practices/1.0/en/):
  source documentation, locality clauses, feature extent and uncertainty remain
  necessary before a location is suitable for release.
- [Mordecai source inspected through GitHits](https://github.com/openeventdata/mordecai/blob/9d37110f/mordecai/geoparse.py):
  NLP extraction and gazetteer lookup were evaluated as separate stages; the
  heavyweight implementation was not installed or copied.
- [spaCy stopword source inspected through GitHits](https://github.com/explosion/spaCy/blob/7ff14d4d/spacy/lang/en/stop_words.py):
  informed the diagnostic distinction between ordinary words and place aliases.
  The library's dataset-specific filters are heuristic, not a trained model.

Reusable code and commands are listed in [README.md](README.md). Full real-data
receipts and exploration outputs are local artifacts and must not be committed.
