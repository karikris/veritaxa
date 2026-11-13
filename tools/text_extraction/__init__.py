"""Text extraction primitives for source-bound location-clue research."""

from .context import country_context, evidence_for_unit, relative_clues
from .coordinates import coordinate_tags, map_coordinates, text_coordinates, valid_coordinates
from .evidence import deduplicate_evidence, safe_frame
from .flickr import source_locations, units
from .gazetteer import Gazetteer
from .html_text import VisibleText, visible
from .temporal import capture_time, temporal_neighbors

__all__ = [
    "Gazetteer",
    "VisibleText",
    "capture_time",
    "coordinate_tags",
    "country_context",
    "deduplicate_evidence",
    "evidence_for_unit",
    "map_coordinates",
    "relative_clues",
    "safe_frame",
    "source_locations",
    "temporal_neighbors",
    "text_coordinates",
    "units",
    "valid_coordinates",
    "visible",
]
