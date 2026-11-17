"""Run with: streamlit run apps/review_map/app.py."""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

# Community Cloud adds the entrypoint directory; the package lives at the repo root.
REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from apps.review_map.core import (  # noqa: E402
    COLOUR_DATE_BOUNDS,
    SnapshotError,
    map_cells,
    selected_csv,
    selection_catalog,
    selection_groups,
)
from apps.review_map.images import Thumbnails, image_response  # noqa: E402
from apps.review_map.regions import REGIONS  # noqa: E402
from apps.review_map.source import load_snapshot  # noqa: E402

HERE = Path(__file__).resolve().parent


def setting(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    try:
        return str(st.secrets.get(name, default))
    except st.errors.StreamlitSecretNotFoundError:
        return default


@st.cache_data(ttl=30, max_entries=2, show_spinner=False)
def snapshot_data(reference: str, local: bool):
    """Load a snapshot or its private deployment pointer."""
    return load_snapshot(reference, local=local)


@st.cache_resource(show_spinner=False)
def thumbnail_cache(directory: str):
    return Thumbnails(Path(directory))


def frontend_assets(frontend: Path) -> tuple[str, str, str]:
    # Read outside the resource cache so an asset-only deploy refreshes the renderer.
    return (
        (frontend / "map.html").read_text(),
        (frontend / "vendor/leaflet.css").read_text() + "\n" + (frontend / "map.css").read_text(),
        (frontend / "vendor/leaflet.js").read_text()
        + "\n"
        + (frontend / "selection.js").read_text()
        + "\n"
        + (frontend / "map.js").read_text(),
    )


@st.cache_resource(show_spinner=False)
def map_component(html: str, css: str, js: str):
    version = hashlib.sha256(repr((html, css, js)).encode()).hexdigest()[:16]
    return st.components.v2.component(
        "review_world_map_" + version,
        html=html,
        css=css,
        js=js,
        isolate_styles=True,
    )


def main():
    st.set_page_config(page_title="Photo map", page_icon="🦋", layout="wide")
    local_path, remote_url = setting("MAP_SNAPSHOT_PATH"), setting("MAP_SNAPSHOT_URL")
    reference = local_path or remote_url
    if not reference:
        st.info("Choose a private map snapshot in the deployment settings.")
        return
    try:
        snapshot = snapshot_data(reference, bool(local_path))
    except SnapshotError as error:
        st.error(str(error))
        return
    st.title(snapshot.title)
    years = st.slider(
        "Photo dates",
        min_value=COLOUR_DATE_BOUNDS[0].year,
        max_value=COLOUR_DATE_BOUNDS[1].year,
        value=(COLOUR_DATE_BOUNDS[0].year, COLOUR_DATE_BOUNDS[1].year),
    )
    if st.session_state.get("map_selection_source") != snapshot.revision:
        st.session_state["map_selection_source"] = snapshot.revision
        st.session_state["map_excluded_keys"] = []
        st.session_state["map_included_keys"] = []
        st.session_state["map_selection_version"] = 0
        st.session_state["map_excluded_regions"] = []
        st.session_state["map_excluded_labels"] = []
        st.session_state["map_limit_csv_dates"] = False
        st.session_state.pop("map_export_response", None)
    cells = map_cells(snapshot, years)
    catalog = selection_catalog(snapshot)
    model_labels = selection_groups(snapshot)
    legacy_labels = set(st.session_state.get("map_excluded_labels", [])) - set(model_labels)
    if legacy_labels:
        previous = set(st.session_state.get("map_excluded_keys", []))
        previous.update(
            photo.key for photo in snapshot.photos if photo.bioclip_label in legacy_labels
        )
        st.session_state["map_excluded_keys"] = list(previous)
        st.session_state["map_excluded_labels"] = [
            label
            for label in st.session_state.get("map_excluded_labels", [])
            if label in model_labels
        ]
        st.session_state["map_selection_version"] = (
            st.session_state.get("map_selection_version", 0) + 1
        )
    view_revision = snapshot.revision + ":" + str(years)
    visible = sum(cell["count"] for cell in cells)
    st.caption(f"{visible:,} photographs · {len(cells):,} locations · 10 km display grid")
    st.markdown(
        '<div style="display:flex;align-items:center;gap:12px;margin:0 0 14px;'
        'font-size:13px"><span>'
        + str(COLOUR_DATE_BOUNDS[0].year)
        + '</span><span style="height:8px;width:190px;border-radius:9px;'
        'background:linear-gradient(90deg,#2563eb,#ef4444)"></span><span>'
        + str(COLOUR_DATE_BOUNDS[1].year)
        + "</span></div>",
        unsafe_allow_html=True,
    )
    photos = {photo.key: photo for photo in snapshot.photos}
    cache = thumbnail_cache(
        setting("MAP_CACHE_DIR", str(Path(tempfile.gettempdir()) / "review-map-thumbnails"))
    )

    def on_photo_request():
        request = st.session_state.get("world_map", {}).get("photo_request")
        if not isinstance(request, dict):
            return
        key, token = request.get("key"), request.get("token")
        if not isinstance(key, str) or not isinstance(token, str) or len(token) > 256:
            return
        photo = photos.get(key)
        if photo is None:
            st.session_state["map_photo_response"] = {"token": token, "unavailable": True}
            return
        st.session_state["map_photo_response"] = image_response(photo, token, cache)

    def on_exclusions():
        request = st.session_state.get("world_map", {}).get("exclusions")
        if not isinstance(request, dict) or request.get("source_revision") != snapshot.revision:
            return
        keys, version = request.get("keys"), request.get("version")
        included_keys = request.get("included_keys", [])
        regions, limit_dates = request.get("regions", []), request.get("limit_dates", False)
        labels = request.get("labels", [])
        if (
            not isinstance(keys, list)
            or len(keys) > len(photos)
            or any(not isinstance(key, str) or key not in photos for key in keys)
            or not isinstance(included_keys, list)
            or len(included_keys) > len(photos)
            or any(not isinstance(key, str) or key not in photos for key in included_keys)
            or not isinstance(regions, list)
            or len(regions) > len(REGIONS)
            or any(not isinstance(region, str) or region not in REGIONS for region in regions)
            or not isinstance(labels, list)
            or len(labels) > len(model_labels)
            or any(not isinstance(label, str) or label not in model_labels for label in labels)
            or not isinstance(limit_dates, bool)
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version <= st.session_state.get("map_selection_version", 0)
        ):
            return
        st.session_state["map_excluded_keys"] = list(set(keys))
        st.session_state["map_included_keys"] = list(set(included_keys))
        st.session_state["map_selection_version"] = version
        st.session_state["map_excluded_regions"] = list(set(regions))
        st.session_state["map_excluded_labels"] = list(set(labels))
        st.session_state["map_limit_csv_dates"] = limit_dates

    def on_export_request():
        request = st.session_state.get("world_map", {}).get("export_request")
        if not isinstance(request, dict):
            return
        token = request.get("token")
        if not isinstance(token, str) or not token or len(token) > 256:
            return
        try:
            if request.get("view_revision") != view_revision:
                raise ValueError("The map changed. Please download again.")
            # The explicit click-time selection avoids racing an exclusions callback.
            limit_dates = request.get("limit_dates", False)
            if not isinstance(limit_dates, bool):
                raise ValueError("Invalid export scope.")
            body = selected_csv(snapshot, request.get("keys"), years if limit_dates else None)
            response = {
                "token": token,
                "csv": base64.b64encode(body).decode("ascii"),
                "filename": "selected-observations.csv",
            }
        except ValueError:
            response = {"token": token, "error": "The map changed. Please download again."}
        st.session_state["map_export_response"] = response

    map_component(*frontend_assets(HERE / "frontend"))(
        data={
            "source_revision": snapshot.revision,
            "revision": view_revision,
            "excluded_keys": st.session_state.get("map_excluded_keys", []),
            "included_keys": st.session_state.get("map_included_keys", []),
            "selection_version": st.session_state.get("map_selection_version", 0),
            "excluded_regions": st.session_state.get("map_excluded_regions", []),
            "excluded_labels": st.session_state.get("map_excluded_labels", []),
            "labels": model_labels,
            "limit_csv_dates": st.session_state.get("map_limit_csv_dates", False),
            "catalog": catalog,
            "regions": REGIONS,
            "export_response": st.session_state.get("map_export_response"),
            "cells": cells,
            "photo_response": st.session_state.get("map_photo_response"),
        },
        key="world_map",
        on_photo_request_change=on_photo_request,
        on_exclusions_change=on_exclusions,
        on_export_request_change=on_export_request,
    )
    st.caption(
        "Hover to preview. Click or tap to keep a photo open. "
        "Exclude an image or its whole location, or use the continent and BioCLIP filters. "
        "CSV downloads include all dates by default. "
        "Bubbles count distinct dates at each location. "
        "Selections apply to this session. Dates use the capture date when reliable, "
        "otherwise the upload date."
    )


if __name__ == "__main__":
    main()
