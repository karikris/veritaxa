"""Export a joined review CSV to three lossless, filtered Excel worksheets.

Usage: python -m tools.csv_to_workbook INPUT.csv [--output OUTPUT.xlsx]
Requires XlsxWriter. Values remain text to preserve identifiers and CSV values.
Long values continue in appended FIELD__part_N columns; concatenate parts in
order to reconstruct the original value. The JSON receipt records this mapping.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import xlsxwriter

CELL_LIMIT = 32767
SHEETS = ("All images", "Classified images", "Non-classified images")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def split_cell(value):
    """Bound UTF-16 units as well as Python characters, including emoji."""
    if len(value.encode("utf-16-le")) // 2 <= CELL_LIMIT:
        return [value]
    parts, start, size = [], 0, 0
    for index, char in enumerate(value):
        units = 2 if ord(char) > 0xFFFF else 1
        if size + units > CELL_LIMIT:
            parts.append(value[start:index])
            start, size = index, 0
        size += units
    parts.append(value[start:])
    return parts


def is_classified(value):
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise ValueError(f"Invalid classification flag: {value!r}")


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        for row in reader:
            if len(row) != len(header):
                raise ValueError(f"Malformed CSV row at line {reader.line_num}")
            yield row


def expanded_row(row, mapping, width):
    expanded = [""] * width
    for value, indices in zip(row, mapping, strict=True):
        for chunk, column in zip(split_cell(value), indices, strict=False):
            expanded[column] = chunk
    return expanded


def excel_text(value):
    # Decode OOXML escaped controls once; escaped literal _xNNNN_ stays literal.
    return re.sub(r"_x([0-9a-fA-F]{4})_", lambda m: chr(int(m[1], 16)), value)


def sheet_rows(archive, sheet_index, width):
    with archive.open(f"xl/worksheets/sheet{sheet_index + 1}.xml") as xml:
        for _, element in ET.iterparse(xml, events=("end",)):
            if element.tag != NS + "row":
                continue
            values = [""] * width
            for cell in element.findall(NS + "c"):
                letters = re.match(r"[A-Z]+", cell.attrib["r"])[0]
                column = 0
                for letter in letters:
                    column = column * 26 + ord(letter) - 64
                values[column - 1] = excel_text("".join(t.text or "" for t in cell.iter(NS + "t")))
                if cell.find(NS + "f") is not None:
                    raise ValueError("Unexpected executable formula")
            yield values
            element.clear()


def classification_group(row, columns):
    """Prefer completed round-two results; do not resolve ties arbitrarily."""
    round_name = "second_round" if int(row.get("second_round_review_count") or 0) else "first_round"
    column = f"{round_name}_strict_majority_result"
    if column not in columns:
        raise ValueError(f"Group export requires {column}")
    result = row[column]
    if not result:
        return "Disputed"
    if result.startswith("target_scientific_name:"):
        return result.split(":", 1)[1]
    return result.replace("_", " ").capitalize()


def destinations(row, columns, classification_index, by_classification):
    flag = is_classified(row[classification_index])
    if by_classification:
        return [classification_group(dict(zip(columns, row, strict=True)), columns)] if flag else []
    return [SHEETS[0], SHEETS[1 if flag else 2]]


def worksheet_names(groups):
    names, used = {}, set()
    for group in groups:
        base = re.sub(r"[\[\]:*?/\\]", " ", group).strip(" '")[:31] or "Group"
        name, suffix = base, 1
        while name.casefold() in used:
            suffix += 1
            tail = f" ({suffix})"
            name = base[: 31 - len(tail)] + tail
        names[group] = name
        used.add(name.casefold())
    return names


def verify(workbook, snapshot, header, mapping, columns, classification_index, groups, grouped):
    width = len(header)
    with zipfile.ZipFile(workbook) as archive:
        for sheet_index, group in enumerate(groups):
            actual = sheet_rows(archive, sheet_index, width)
            if next(actual) != header:
                raise ValueError("Workbook header differs from CSV mapping")
            for row in read_rows(snapshot):
                if group not in destinations(row, columns, classification_index, grouped):
                    continue
                if next(actual, None) != expanded_row(row, mapping, width):
                    raise ValueError(f"Workbook round-trip mismatch in {group}")
            if next(actual, None) is not None:
                raise ValueError("Unexpected extra workbook rows")


def export_workbook(
    source, output, classification_column="has_saved_review", by_classification=False
):
    csv.field_size_limit(100_000_000)
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError("Input and output must differ")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".xlsx-export-", dir=output.parent) as temp:
        snapshot = Path(temp) / "input.csv"
        with source.open("rb") as src, snapshot.open("wb") as dest:
            shutil.copyfileobj(src, dest)
        with snapshot.open(encoding="utf-8-sig", newline="") as stream:
            original = next(csv.reader(stream))
        if not original or len(original) != len(set(original)):
            raise ValueError("CSV must have unique, nonempty headers")
        if any(not h or len(split_cell(h)) != 1 for h in original):
            raise ValueError("Invalid or oversized CSV header")
        classification_index = original.index(classification_column)
        counts = {} if by_classification else dict.fromkeys(SHEETS, 0)
        capacities = [1] * len(original)
        total_rows = 0
        for row in read_rows(snapshot):
            total_rows += 1
            for group in destinations(row, original, classification_index, by_classification):
                counts[group] = counts.get(group, 0) + 1
            for i, value in enumerate(row):
                capacities[i] = max(capacities[i], len(split_cell(value)))
        header = original.copy()
        mapping = [[i] for i in range(len(original))]
        for i, capacity in enumerate(capacities):
            for part in range(2, capacity + 1):
                name = f"{original[i]}__part_{part}"
                if name in header:
                    raise ValueError(f"Continuation column collides with CSV column: {name}")
                mapping[i].append(len(header))
                header.append(name)
        if not counts:
            raise ValueError("No classified images to export")
        if by_classification:
            counts = dict(sorted(counts.items(), key=lambda item: (item[0] == "Disputed", item[0])))
        names = worksheet_names(counts)
        if len(header) > 16384 or max(counts.values()) > 1048575:
            raise ValueError("Dataset exceeds Excel worksheet dimensions")
        target = Path(temp) / "workbook.xlsx"
        with xlsxwriter.Workbook(
            target,
            {
                "constant_memory": True,
                "strings_to_formulas": False,
                "strings_to_urls": False,
                "strings_to_numbers": False,
            },
        ) as book:
            book.set_properties(
                {
                    "title": "Image classifications and original metadata",
                    "comments": (
                        "CSV values preserved as text; long values continue in __part_N columns."
                    ),
                }
            )
            style = book.add_format(
                {"bold": True, "bg_color": "#173D51", "font_color": "#FFFFFF", "text_wrap": True}
            )
            sheets = {group: book.add_worksheet(name) for group, name in names.items()}
            for group, sheet in sheets.items():
                count = counts[group]
                sheet.freeze_panes(1, 3)
                sheet.autofilter(0, 0, count, len(header) - 1)
                sheet.set_row(0, 32)
                sheet.set_column(0, len(header) - 1, 22)
                for i, name in enumerate(header):
                    if sheet.write_string(0, i, name, style) != 0:
                        raise ValueError("Excel rejected header")
                for i, indices in enumerate(mapping):
                    if len(indices) > 1:
                        sheet.write_comment(
                            0,
                            i,
                            "Full value = this column followed by "
                            + ", ".join(header[c] for c in indices[1:]),
                        )
            positions = dict.fromkeys(counts, 1)
            for row in read_rows(snapshot):
                values = expanded_row(row, mapping, len(header))
                for destination in destinations(
                    row, original, classification_index, by_classification
                ):
                    for column, value in enumerate(values):
                        if (
                            value
                            and sheets[destination].write_string(
                                positions[destination], column, value
                            )
                            != 0
                        ):
                            raise ValueError("Excel rejected a CSV value")
                    positions[destination] += 1
        verify(
            target,
            snapshot,
            header,
            mapping,
            original,
            classification_index,
            counts,
            by_classification,
        )
        receipt = {
            "input": str(source),
            "input_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "output": str(output),
            "sheet_rows": {names[group]: count for group, count in counts.items()},
            "classification_groups": names if by_classification else None,
            "input_rows": total_rows,
            "grouping": "latest completed round strict majority; ties disputed"
            if by_classification
            else "review presence",
            "original_columns": len(original),
            "workbook_columns": len(header),
            "continuation_columns": {
                original[i]: [header[c] for c in indices]
                for i, indices in enumerate(mapping)
                if len(indices) > 1
            },
            "classification_column": classification_column,
            "values_stored_as": "text",
            "all_cells_roundtrip_verified": True,
        }
        os.replace(target, output)
        output.with_suffix(".xlsx.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--classification-column", default="has_saved_review")
    parser.add_argument(
        "--by-classification",
        action="store_true",
        help="One populated tab per majority result, plus Disputed for ties",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            export_workbook(
                args.input,
                args.output
                or args.input.with_name(
                    args.input.stem
                    + ("_by_classification.xlsx" if args.by_classification else ".xlsx")
                ),
                args.classification_column,
                args.by_classification,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
