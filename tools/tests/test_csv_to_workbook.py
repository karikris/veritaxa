import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.csv_to_workbook import export_workbook, sheet_rows, split_cell, worksheet_names


class WorkbookTests(unittest.TestCase):
    def make_csv(self, directory, header, rows):
        path = Path(directory) / "input.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def test_lossless_three_tabs_and_future_metadata(self):
        long = "😀" * 18000 + "tail"
        tricky = '=HYPERLINK("https://example.com", "literal")\r\n_x000D_\x01'
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_csv(
                temp,
                ["photo_id", "has_saved_review", "description", "new_metadata"],
                [["00123", "true", long, tricky], ["00999", "false", "", "https://example.com"]],
            )
            out = Path(temp) / "out.xlsx"
            receipt = export_workbook(path, out)
            self.assertEqual(
                receipt["sheet_rows"],
                {"All images": 2, "Classified images": 1, "Non-classified images": 1},
            )
            self.assertEqual(receipt["workbook_columns"], 5)
            with zipfile.ZipFile(out) as archive:
                all_rows = list(sheet_rows(archive, 0, 5))
                self.assertEqual(all_rows[1][0], "00123")
                self.assertEqual(all_rows[1][2] + all_rows[1][4], long)
                self.assertEqual(all_rows[1][3], tricky)
                self.assertNotIn(b"<hyperlinks", archive.read("xl/worksheets/sheet1.xml"))

    def test_utf16_boundaries(self):
        for text in ("x" * 32767, "a" * 32766 + "😀end", "😀" * 40000):
            parts = split_cell(text)
            self.assertEqual("".join(parts), text)
            self.assertTrue(all(len(p.encode("utf-16-le")) // 2 <= 32767 for p in parts))

    def test_empty_classified_tab(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_csv(temp, ["has_saved_review"], [["false"]])
            result = export_workbook(path, Path(temp) / "out.xlsx")
            self.assertEqual(result["sheet_rows"]["Classified images"], 0)

    def test_invalid_flag_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_csv(temp, ["has_saved_review"], [["unknown"]])
            out = Path(temp) / "out.xlsx"
            out.write_bytes(b"existing")
            with self.assertRaises(ValueError):
                export_workbook(path, out)
            self.assertEqual(out.read_bytes(), b"existing")

    def test_classification_groups_include_ties_and_prefer_round_two(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_csv(
                temp,
                [
                    "photo_id",
                    "has_saved_review",
                    "first_round_strict_majority_result",
                    "second_round_review_count",
                    "second_round_strict_majority_result",
                ],
                [
                    ["1", "true", "target_scientific_name:Papilio demoleus", "0", ""],
                    ["2", "true", "adult_butterfly", "1", "caterpillar"],
                    ["3", "true", "", "0", ""],
                    ["4", "false", "", "0", ""],
                ],
            )
            out = Path(temp) / "groups.xlsx"
            result = export_workbook(path, out, by_classification=True)
            self.assertEqual(
                result["sheet_rows"],
                {
                    "Caterpillar": 1,
                    "Papilio demoleus": 1,
                    "Disputed": 1,
                },
            )
            with zipfile.ZipFile(out) as archive:
                self.assertEqual(list(sheet_rows(archive, 0, 5))[1][0], "2")

    def test_group_sheet_names_are_unique_and_excel_safe(self):
        groups = ["a/b", "a:b", "A B", "x" * 40, "x" * 41]
        names = worksheet_names(groups)
        self.assertEqual(len({n.casefold() for n in names.values()}), len(groups))
        self.assertTrue(all(len(n) <= 31 for n in names.values()))
        self.assertTrue(all("/" not in n and ":" not in n for n in names.values()))


if __name__ == "__main__":
    unittest.main()
