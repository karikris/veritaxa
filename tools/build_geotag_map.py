"""Build a self-contained private map from an administrative geotag snapshot."""

import argparse
import json
from pathlib import Path


def script_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def build(records: Path, assets: Path, output: Path):
    rows = json.loads(records.read_text())
    world = json.loads((assets / "countries.geojson").read_text())
    for feature in world["features"]:
        properties = feature["properties"]
        feature["properties"] = {
            "name": properties.get("NAME"),
            "country": properties.get("ISO_A2_EH"),
        }
    html = Path(__file__).with_name("geotag_map_template.html").read_text()
    html = html.replace("__LEAFLET_CSS__", (assets / "leaflet.css").read_text())
    html = html.replace(
        "__LEAFLET_JS__", (assets / "leaflet.js").read_text().replace("</script", "<\\/script")
    )
    html = html.replace("__RECORDS_JSON__", script_json(rows))
    html = html.replace("__WORLD_JSON__", script_json(world))
    output.write_text(html)
    output.chmod(0o600)
    return {
        "images": len(rows),
        "mapped": sum(r.get("latitude") is not None for r in rows),
        "bytes": output.stat().st_size,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--records", type=Path, required=True)
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.records, a.assets, a.output)))


if __name__ == "__main__":
    main()
