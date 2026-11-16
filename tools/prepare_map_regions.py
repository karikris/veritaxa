"""Reduce a public Natural Earth 5.1.2 50m map-units GeoJSON for offline region lookup."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def build(source: Path, destination: Path):
    body = source.read_bytes()
    features = json.loads(body)["features"]
    polygons = []
    for feature in features:
        props, geometry = feature["properties"], feature["geometry"]
        region = props["CONTINENT"]
        if region == "Africa":
            region = (
                "North Africa" if props["SUBREGION"] == "Northern Africa" else "Sub-Saharan Africa"
            )
        elif region == "Seven seas (open ocean)":
            region = "Other / offshore"
        parts = (
            [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        )
        for part in parts:
            rings = [[[round(x, 4), round(y, 4)] for x, y in ring] for ring in part]
            xs, ys = zip(*rings[0], strict=True)
            polygons.append(
                {"region": region, "bbox": [min(xs), min(ys), max(xs), max(ys)], "rings": rings}
            )
    result = {
        "source": "Natural Earth 5.1.2, 50m admin-0 map units",
        "source_sha256": hashlib.sha256(body).hexdigest(),
        "polygons": polygons,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.source, args.destination)
