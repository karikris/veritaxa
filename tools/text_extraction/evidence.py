"""Stable evidence identities, occurrence counts and structured output frames."""

import hashlib

import polars as pl

from .common import dump

COMMON_EVIDENCE_SCHEMA = {
    "flickr_photo_id": pl.String,
    "source": pl.String,
    "field": pl.String,
    "author_is_owner": pl.Boolean,
    "comment_id": pl.String,
    "comment_author": pl.String,
    "comment_created_at": pl.String,
}
OUTPUT_SCHEMAS = {
    "location_evidence": dict(
        COMMON_EVIDENCE_SCHEMA,
        kind=pl.String,
        matched_text=pl.String,
        excerpt=pl.String,
        candidates=pl.String,
        candidate_count=pl.Int64,
        flags=pl.String,
        capture_locality_candidate=pl.Boolean,
        evidence_id=pl.String,
        occurrence_count=pl.Int64,
    ),
    "relative_time_evidence": dict(
        COMMON_EVIDENCE_SCHEMA,
        expression=pl.String,
        minutes=pl.Float64,
        direction=pl.String,
        reference_basis=pl.String,
        narrative_type=pl.String,
        excerpt=pl.String,
    ),
    "temporal_geotagged_neighbors": {
        **dict.fromkeys(
            [
                "flickr_photo_id",
                "owner_id",
                "target_capture_time",
                "anchor_flickr_photo_id",
                "anchor_capture_time",
                "target_photo_page_url",
                "target_title",
                "anchor_title",
                "anchor_description_excerpt",
                "anchor_photo_page_url",
                "anchor_method",
                "relation",
                "time_window",
                "time_basis",
                "inference_status",
            ],
            pl.String,
        ),
        "anchor_latitude": pl.Float64,
        "anchor_longitude": pl.Float64,
        "anchor_coordinate_accuracy": pl.Int64,
        "minutes_anchor_before_target": pl.Float64,
        "matching_anchor_count": pl.Int64,
    },
}


def safe_frame(records, schema=None):
    if not records:
        return pl.DataFrame(schema=schema or {})
    frame = pl.DataFrame(
        [{k: dump(v) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in records],
        infer_schema_length=None,
    )
    for field, dtype in (schema or {}).items():
        if field not in frame:
            frame = frame.with_columns(pl.lit(None, dtype=dtype).alias(field))
        elif frame.schema[field] == pl.Null:
            frame = frame.with_columns(pl.col(field).cast(dtype))
    return frame


def deduplicate_evidence(records):
    unique = {}
    for record in records:
        identity = {k: v for k, v in record.items() if k not in {"evidence_id", "occurrence_count"}}
        key = record.get("evidence_id") or hashlib.sha256(dump(identity).encode()).hexdigest()
        if key in unique:
            existing = {
                k: v for k, v in unique[key].items() if k not in {"evidence_id", "occurrence_count"}
            }
            if existing != identity:
                raise ValueError("Conflicting evidence payloads share the same evidence_id")
            unique[key]["occurrence_count"] += record.get("occurrence_count", 1)
        else:
            unique[key] = dict(
                record, evidence_id=key, occurrence_count=record.get("occurrence_count", 1)
            )
    return list(unique.values())
