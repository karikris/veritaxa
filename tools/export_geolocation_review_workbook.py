"""Build four disjoint location-review worksheets from human classifications.

Reuses the lossless CSV/Excel text helpers. Source metadata and saved reviews
remain intact; only additional, nonduplicate location columns are joined.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import polars as pl
import xlsxwriter

from tools.csv_to_workbook import expanded_row, read_rows, sheet_rows, split_cell
from tools.text_extraction.common import digest

GROUPS = ("Priority review", "Other location hints", "Profile-only hints", "No location hints")
PRIORITY_STATES = {
    "public_flickr_coordinates_recovered",
    "coordinate_machine_tags_require_review",
    "text_coordinate_references_require_review",
    "named_capture_locality_candidate",
    "same_owner_geotagged_neighbor_within_1_hour",
}
OTHER_STATES = {
    "text_location_clues_require_review",
    "relative_time_clue_only",
    "same_owner_geotagged_neighbor_within_24_hours",
}
COMPUTED = {
    "workbook_location_group",
    "location_hint_summary",
    "reviewer_names",
    "reviewers_with_target_label",
}


def parsed(value, default=None):
    if value is None or value == "":
        return default
    return json.loads(value) if isinstance(value, str) else value


def priority_hint(row):
    return (
        row.get("provider_latitude") is not None
        or bool(parsed(row.get("coordinate_machine_tags_json")))
        or bool(parsed(row.get("text_coordinate_clues_json")))
        or bool(parsed(row.get("named_locality_candidates_json")))
        or (row.get("geotagged_neighbors_within_1_hour") or 0) > 0
    )


def location_group(row):
    if priority_hint(row):
        return GROUPS[0]
    status = row.get("location_clue_status")
    if status == "owner_profile_only_not_photo_location":
        return GROUPS[2]
    if status == "no_supported_location_clue_found":
        return GROUPS[3]
    if status in OTHER_STATES:
        return GROUPS[1]
    raise ValueError(f"Unrecognized or inconsistent location status: {status!r}")


def hint_summary(row):
    parts = []
    if row.get("provider_latitude") is not None:
        parts.append(
            f"Public Flickr coordinates: {row['provider_latitude']}, "
            f"{row.get('provider_longitude')}"
        )
    if parsed(row.get("coordinate_machine_tags_json")):
        parts.append("Raw coordinate tags available; source needs review")
    if parsed(row.get("text_coordinate_clues_json")):
        parts.append("Coordinates mentioned in text; may describe a named feature")
    places = parsed(row.get("named_locality_candidates_json"), [])
    names = list(
        dict.fromkeys(
            ", ".join(filter(None, [p.get("name"), p.get("country_name")])) for p in places
        )
    )
    if names:
        parts.append("Place candidates: " + "; ".join(names))
    neighbor = parsed(row.get("closest_geotagged_neighbor_json"))
    if neighbor:
        minutes = neighbor["minutes_anchor_before_target"]
        direction = "earlier" if minutes > 0 else "later" if minutes < 0 else "at the same time"
        parts.append(f"Same-owner geotagged photo {abs(minutes):.2f} minutes {direction}")
    if row.get("location_clue_status") == "owner_profile_only_not_photo_location":
        parts.append(
            "Profile location only; not a capture location: "
            + str(row.get("owner_profile_location") or "")
        )
    if not parts:
        parts.append(
            "No supported location clue found"
            if location_group(row) == GROUPS[3]
            else "Weaker text or timing mentions require review"
        )
    return " | ".join(parts)


def load_frame(path):
    return (
        pl.read_parquet(path)
        if path.suffix.lower() == ".parquet"
        else pl.read_csv(
            path, schema_overrides={"flickr_photo_id": pl.String}, infer_schema_length=None
        )
    )


def build_records(metadata, clues, target="Papilio demoleus", round_name="first_round"):
    for frame in (metadata, clues):
        if (
            frame["flickr_photo_id"].null_count()
            or frame["flickr_photo_id"].n_unique() != frame.height
        ):
            raise ValueError("Each input must have unique, non-null Flickr photo IDs")
        if COMPUTED.intersection(frame.columns):
            raise ValueError("Input contains computed workbook columns; use the source exports")
    key = f"target_scientific_name:{target}"
    selected = [
        r
        for r in metadata.to_dicts()
        if (parsed(r.get(f"{round_name}_result_counts_json"), {}) or {}).get(key, 0) > 0
    ]
    if not selected:
        raise ValueError("No human classifications match the requested scientific name")
    geo = {str(r["flickr_photo_id"]): r for r in clues.to_dicts()}
    # These aliases repeat existing human-review or title fields in the source.
    aliases = {"has_saved_human_review", "human_majority_label", "title"}
    addition_columns = [c for c in clues.columns if c not in metadata.columns and c not in aliases]
    rows = []
    for original in selected:
        photo_id = str(original["flickr_photo_id"])
        if photo_id not in geo:
            raise ValueError(f"Missing location analysis for Flickr photo ID {photo_id}")
        row = dict(original)
        row.update({c: geo[photo_id][c] for c in addition_columns})
        reviews = parsed(row.get(f"{round_name}_reviews_json"), [])
        positives = [r for r in reviews if r.get("result") == key]
        if not positives:
            raise ValueError("Human result counts disagree with saved review details")

        def name(review):
            return (
                review.get("reviewer_profile_name")
                or review.get("reviewer_name")
                or review.get("reviewer_uuid")
                or "Unknown reviewer"
            )

        row["reviewer_names"] = "; ".join(sorted({name(r) for r in reviews}))
        row["reviewers_with_target_label"] = "; ".join(sorted({name(r) for r in positives}))
        row["workbook_location_group"] = location_group(row)
        row["location_hint_summary"] = hint_summary(row)
        rows.append(row)
    leading = [
        "flickr_photo_id",
        "flickr_current_title",
        "photo_page_url",
        "image_url",
        "location_hint_summary",
        "reviewer_names",
        "reviewers_with_target_label",
        f"{round_name}_has_conflicting_reviews",
        f"{round_name}_unanimous_result",
        "location_clue_status",
        "workbook_location_group",
    ]
    columns = list(dict.fromkeys(c for c in leading + list(rows[0]) if c in rows[0]))
    return rows, columns


def text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def export_workbook(
    source, clue_source, output, target="Papilio demoleus", round_name="first_round"
):
    csv.field_size_limit(100_000_000)
    source, clue_source, output = map(lambda p: Path(p).absolute(), (source, clue_source, output))
    if output in (source, clue_source):
        raise ValueError("Workbook output must differ from both inputs")
    before_hashes = {"metadata": digest(source), "location_clues": digest(clue_source)}
    metadata, clues = load_frame(source), load_frame(clue_source)
    rows, columns = build_records(metadata, clues, target, round_name)
    counts = Counter(r["workbook_location_group"] for r in rows)
    group_index = columns.index("workbook_location_group")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".geolocation-workbook-", dir=output.parent
    ) as temporary:
        temporary = Path(temporary)
        snapshot = temporary / "joined.csv"
        capacities = [1] * len(columns)
        with snapshot.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(columns)
            for record in rows:
                values = [text(record.get(c)) for c in columns]
                writer.writerow(values)
                for i, value in enumerate(values):
                    capacities[i] = max(capacities[i], len(split_cell(value)))
        header = columns.copy()
        mapping = [[i] for i in range(len(columns))]
        for i, capacity in enumerate(capacities):
            for part in range(2, capacity + 1):
                name = f"{columns[i]}__part_{part}"
                if name in header:
                    raise ValueError("Continuation-column name collides with an existing column")
                mapping[i].append(len(header))
                header.append(name)
        if len(header) > 16384 or max(counts.values()) > 1048575:
            raise ValueError("Workbook exceeds Excel worksheet dimensions")
        names = {g: f"{i + 1} {g} ({counts[g]})"[:31] for i, g in enumerate(GROUPS)}
        target_file = temporary / "workbook.xlsx"
        with xlsxwriter.Workbook(
            target_file,
            {
                "constant_memory": True,
                "strings_to_formulas": False,
                "strings_to_urls": False,
                "strings_to_numbers": False,
            },
        ) as book:
            book.set_properties(
                {
                    "title": f"{target}: geolocation review groups",
                    "comments": (
                        "Human target labels include disagreements. "
                        "Location hints require review. "
                        "Long source values continue in __part_N columns."
                    ),
                }
            )
            style = book.add_format(
                {"bold": True, "font_color": "white", "bg_color": "#173D51", "text_wrap": True}
            )
            sheets = {g: book.add_worksheet(names[g]) for g in GROUPS}
            for group, sheet in sheets.items():
                sheet.freeze_panes(1, 2)
                sheet.autofilter(0, 0, counts[group], len(header) - 1)
                sheet.set_row(0, 38)
                sheet.set_column(0, len(header) - 1, 22)
                sheet.set_column(0, 0, 16)
                sheet.set_column(
                    columns.index("location_hint_summary"),
                    columns.index("location_hint_summary"),
                    65,
                )
                for i, name in enumerate(header):
                    if sheet.write_string(0, i, name, style) != 0:
                        raise ValueError("Excel rejected a column header")
                sheet.write_comment(
                    0,
                    group_index,
                    "Tabs are disjoint: priority hints, other hints, profile-only, then no hints. "
                    "Profile locations do not establish capture sites.",
                )
                for i, indices in enumerate(mapping):
                    if len(indices) > 1:
                        sheet.write_comment(
                            0,
                            i,
                            "Concatenate this column with "
                            + ", ".join(header[c] for c in indices[1:]),
                        )
            positions = dict.fromkeys(GROUPS, 1)
            for row in read_rows(snapshot):
                group = row[group_index]
                for i, value in enumerate(expanded_row(row, mapping, len(header))):
                    if not value:
                        continue
                    if (
                        i < len(columns)
                        and columns[i] in {"photo_page_url", "image_url"}
                        and urlparse(value).scheme in {"https", "http"}
                        and len(value) <= 2079
                    ):
                        result = sheets[group].write_url(positions[group], i, value, string=value)
                    else:
                        result = sheets[group].write_string(positions[group], i, value)
                    if result != 0:
                        raise ValueError("Excel rejected a source value")
                positions[group] += 1
        seen = set()
        with zipfile.ZipFile(target_file) as archive:
            for index, group in enumerate(GROUPS):
                actual = sheet_rows(archive, index, len(header))
                if next(actual) != header:
                    raise ValueError("Workbook header round trip failed")
                for row in read_rows(snapshot):
                    if row[group_index] != group:
                        continue
                    if row[columns.index("flickr_photo_id")] in seen:
                        raise ValueError("An image occurs in more than one worksheet")
                    seen.add(row[columns.index("flickr_photo_id")])
                    if next(actual, None) != expanded_row(row, mapping, len(header)):
                        raise ValueError(f"Workbook value round trip failed in {group}")
                if next(actual, None) is not None:
                    raise ValueError("Workbook contains unexpected extra rows")
        if len(seen) != len(rows):
            raise ValueError("Workbook image count differs from the selected cohort")
        if before_hashes != {"metadata": digest(source), "location_clues": digest(clue_source)}:
            raise ValueError("An input changed during workbook creation")
        os.replace(target_file, output)
    receipt = {
        "workbook": str(output),
        "target": target,
        "round": round_name,
        "classification_rule": "At least one saved human target classification; conflicts retained",
        "images": len(rows),
        "conflicting_classifications": sum(
            bool(r.get(f"{round_name}_has_conflicting_reviews")) for r in rows
        ),
        "sheets": {names[g]: counts[g] for g in GROUPS},
        "source_sha256": before_hashes,
        "metadata_columns_preserved": metadata.columns,
        "source_columns": len(columns),
        "excel_columns": len(header),
        "continuations": {
            columns[i]: [header[j] for j in indices]
            for i, indices in enumerate(mapping)
            if len(indices) > 1
        },
        "all_cell_values_verified": True,
        "all_images_exactly_once": True,
        "xlsx_sha256": digest(output),
    }
    output.with_suffix(output.suffix + ".json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--clues", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", default="Papilio demoleus")
    parser.add_argument(
        "--round", dest="round_name", default="first_round", choices=("first_round", "second_round")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            export_workbook(args.source, args.clues, args.output, args.target, args.round_name),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
