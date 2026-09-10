"""Shared candidate normalization for eager compatibility and bounded import paths."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from tools.common import AdminError, optional_https_url, validate_https_url

REQUIRED_COLUMNS = {"image_id", "image_url", "source_provider"}
KNOWN_COLUMNS = {
    *REQUIRED_COLUMNS,
    "display_url",
    "source_record_id",
    "source_page_url",
    "flickr_search_term",
    "source_labels",
    "flickr_labels_json",
    "pipeline_metadata",
}


@dataclass(frozen=True, slots=True)
class Candidate:
    image_id: str
    image_url: str
    display_url: str | None
    source_provider: str
    source_record_id: str | None
    source_page_url: str | None
    flickr_search_term: str | None
    source_labels: Any
    pipeline_metadata: dict[str, Any] | None


def candidate_from_row(row: dict[str, Any]) -> Candidate:
    image_id = _required_text(row.get("image_id"), "image_id", 500)
    provider = _required_text(row.get("source_provider"), "source_provider", 120)
    source_labels_value = row.get("source_labels")
    if _is_missing(source_labels_value):
        source_labels_value = row.get("flickr_labels_json")
    source_labels = _json_value(source_labels_value, "source_labels")

    metadata = _json_value(row.get("pipeline_metadata"), "pipeline_metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise AdminError("pipeline_metadata must be a JSON object when provided.")
    extras = {
        key: _json_safe(value)
        for key, value in row.items()
        if key not in KNOWN_COLUMNS and not _is_missing(value)
    }
    combined_metadata = {**(metadata or {}), **extras} or None

    return Candidate(
        image_id=image_id,
        image_url=validate_https_url(row.get("image_url"), "image_url"),
        display_url=optional_https_url(_none_if_missing(row.get("display_url")), "display_url"),
        source_provider=provider,
        source_record_id=_optional_text(_none_if_missing(row.get("source_record_id")), 500),
        source_page_url=optional_https_url(
            _none_if_missing(row.get("source_page_url")), "source_page_url"
        ),
        flickr_search_term=_optional_text(_none_if_missing(row.get("flickr_search_term")), 1000),
        source_labels=source_labels,
        pipeline_metadata=combined_metadata,
    )


def _json_value(value: object, field: str) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise AdminError(f"{field} must contain valid JSON.") from error
    return _json_safe(value)


def _json_safe(value: object) -> Any:
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def _required_text(value: object, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise AdminError(f"{field} must be non-empty and no longer than {max_length} characters.")
    return value.strip()


def _optional_text(value: object, max_length: int) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > max_length:
        raise AdminError(f"Optional text values must be no longer than {max_length} characters.")
    return value.strip() or None


def _none_if_missing(value: object) -> object | None:
    return None if _is_missing(value) else value


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))
