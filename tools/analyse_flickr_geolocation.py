"""Extract reviewable Flickr location clues using the text-extraction library."""

from tools.text_extraction import (
    Gazetteer,
    VisibleText,
    capture_time,
    coordinate_tags,
    country_context,
    deduplicate_evidence,
    evidence_for_unit,
    map_coordinates,
    relative_clues,
    safe_frame,
    source_locations,
    temporal_neighbors,
    text_coordinates,
    units,
    valid_coordinates,
    visible,
)
from tools.text_extraction.cli import main
from tools.text_extraction.pipeline import analyse, snapshot

__all__ = [
    "Gazetteer",
    "VisibleText",
    "analyse",
    "capture_time",
    "coordinate_tags",
    "country_context",
    "deduplicate_evidence",
    "evidence_for_unit",
    "main",
    "map_coordinates",
    "relative_clues",
    "safe_frame",
    "snapshot",
    "source_locations",
    "temporal_neighbors",
    "text_coordinates",
    "units",
    "valid_coordinates",
    "visible",
]

if __name__ == "__main__":
    main()
