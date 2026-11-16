"""Asset-only deployments must refresh a cached component renderer."""

from apps.review_map.app import frontend_assets, map_component


def test_frontend_asset_changes_invalidate_component_resource(monkeypatch, tmp_path):
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    for relative, text in {
        "map.html": "<section>version one</section>",
        "map.css": ".map {color: blue}",
        "map.js": "export default function () {}",
        "selection.js": "export function syntheticSelection() {}",
        "vendor/leaflet.css": ".leaflet {}",
        "vendor/leaflet.js": "/* synthetic vendor */",
    }.items():
        (tmp_path / relative).write_text(text)
    registrations = []

    def register(name, **assets):
        renderer = object()
        registrations.append((name, assets, renderer))
        return renderer

    monkeypatch.setattr("streamlit.components.v2.component", register)
    map_component.clear()
    try:
        original = map_component(*frontend_assets(tmp_path))
        assert map_component(*frontend_assets(tmp_path)) is original
        for path, new_text in [
            ("map.js", "export default function () { /* new bounds */ }"),
            ("selection.js", "export function syntheticSelection() { return true; }"),
            ("map.html", "<section>new dropdown</section>"),
            ("map.css", ".map {color: red}"),
        ]:
            (tmp_path / path).write_text(new_text)
            renderer = map_component(*frontend_assets(tmp_path))
            assert renderer is not original
            original = renderer
        assert len(registrations) == 5
        assert len({name for name, _, _ in registrations}) == 5
        assert registrations[-1][1]["html"] == "<section>new dropdown</section>"
    finally:
        map_component.clear()
