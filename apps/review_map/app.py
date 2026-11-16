"""Run with: streamlit run apps/review_map/app.py."""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

# Community Cloud adds the entrypoint directory; the package lives at the repo root.
REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from apps.review_map.core import SnapshotError, map_cells, selected_csv  # noqa: E402
from apps.review_map.images import Thumbnails, image_response  # noqa: E402
from apps.review_map.source import load_snapshot  # noqa: E402

HERE = Path(__file__).resolve().parent


def setting(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    try:
        return str(st.secrets.get(name, default))
    except st.errors.StreamlitSecretNotFoundError:
        return default


@st.cache_data(ttl=300, max_entries=2, show_spinner=False)
def snapshot_data(reference: str, local: bool):
    return load_snapshot(reference, local=local)


@st.cache_resource(show_spinner=False)
def thumbnail_cache(directory: str):
    return Thumbnails(Path(directory))


@st.cache_resource(show_spinner=False)
def map_component():
    frontend = HERE / "frontend"
    return st.components.v2.component(
        "review_world_map",
        html=(frontend / "map.html").read_text(),
        css=(frontend / "vendor/leaflet.css").read_text()
        + "\n"
        + (frontend / "map.css").read_text(),
        js=(frontend / "vendor/leaflet.js").read_text() + "\n" + (frontend / "map.js").read_text(),
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
    bounds = snapshot.date_bounds
    years = None
    if bounds[0] and bounds[1] and bounds[0].year != bounds[1].year:
        years = st.slider(
            "Photo dates",
            min_value=bounds[0].year,
            max_value=bounds[1].year,
            value=(bounds[0].year, bounds[1].year),
        )
    if st.session_state.get("map_selection_source") != snapshot.revision:
        st.session_state["map_selection_source"] = snapshot.revision
        st.session_state["map_excluded_keys"] = []
        st.session_state["map_selection_version"] = 0
        st.session_state.pop("map_export_response", None)
    cells = map_cells(snapshot, years)
    view_revision = snapshot.revision + ":" + str(years)
    visible = sum(cell["count"] for cell in cells)
    st.caption(f"{visible:,} photographs · {len(cells):,} locations · 10 km display grid")
    if bounds[0] and bounds[1]:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:12px;margin:0 0 14px;'
            'font-size:13px"><span>'
            + str(bounds[0].year)
            + '</span><span style="height:8px;width:190px;border-radius:9px;'
            'background:linear-gradient(90deg,#2563eb,#ef4444)"></span><span>'
            + str(bounds[1].year)
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
        if (
            not isinstance(keys, list)
            or len(keys) > len(photos)
            or any(not isinstance(key, str) or key not in photos for key in keys)
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version <= st.session_state.get("map_selection_version", 0)
        ):
            return
        st.session_state["map_excluded_keys"] = list(set(keys))
        st.session_state["map_selection_version"] = version

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
            body = selected_csv(snapshot, request.get("keys"), years)
            response = {
                "token": token,
                "csv": base64.b64encode(body).decode("ascii"),
                "filename": "selected-observations.csv",
            }
        except ValueError:
            response = {"token": token, "error": "The map changed. Please download again."}
        st.session_state["map_export_response"] = response

    map_component()(
        data={
            "source_revision": snapshot.revision,
            "revision": view_revision,
            "excluded_keys": st.session_state.get("map_excluded_keys", []),
            "selection_version": st.session_state.get("map_selection_version", 0),
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
        "Uncheck Include in CSV to exclude a photograph from downloads. "
        "Selections apply to this session. Dates use the capture date when reliable, "
        "otherwise the upload date."
    )


if __name__ == "__main__":
    main()
