from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.common import AdminError
from tools.create_rereview_round import (
    category_filename,
    export_snapshots,
    publication_sql,
    regroup_sql,
    snapshot_query,
)


def member(category: str, identifier: str, votes: int = 1) -> dict[str, object]:
    return {
        "item_id": identifier,
        "source_provider": "synthetic",
        "image_id": "same-image",
        "image_url": "https://images.example.invalid/synthetic.jpg",
        "display_url": None,
        "target_scientific_name": "Papilio exemplaris",
        "campaign_code": "REREVIEW-SYNTH-001",
        "batch_code": "RR-SYNTH-001-001",
        "position": 1,
        "provenance": {
            "round_code": "SYNTH",
            "category": category,
            "original_item_id": "original-synthetic",
            "snapshot_at": "2026-01-01T00:00:00Z",
            "source_reviews": [
                {
                    "id": f"{identifier}-vote-{i}",
                    "label": category,
                    "updated_at": "2026-01-01T00:00:00Z",
                    "comment": "Synthetic comment",
                }
                for i in range(votes)
            ],
        },
    }


def test_exports_all_votes_and_conflicting_category_memberships(tmp_path: Path) -> None:
    output = tmp_path / "private"
    records = [member("caterpillar", "first", 2), member("moth", "second")]
    summary = export_snapshots(iter(records), output)
    assert (summary["images"], summary["unique_images"], summary["reviews"]) == (2, 1, 3)
    assert len(summary["categories"]) == 2
    with sqlite3.connect(output / "all-reviews.sqlite3") as db:
        assert db.execute("select count(*) from reviews").fetchone() == (3,)
        assert db.execute("pragma integrity_check").fetchone() == ("ok",)
        original = json.loads(db.execute("select original_review_json from reviews").fetchone()[0])
        assert original["comment"] == "Synthetic comment"
    with sqlite3.connect(output / category_filename("caterpillar")) as db:
        assert db.execute("select count(*) from reviews").fetchone() == (2,)
        assert db.execute("select distinct category from images").fetchall() == [("caterpillar",)]
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())


def test_failed_export_leaves_no_partial_directory(tmp_path: Path) -> None:
    output = tmp_path / "private"

    def failing():
        yield member("caterpillar", "first")
        raise RuntimeError("Synthetic interruption")

    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        export_snapshots(failing(), output)
    assert not output.exists()
    assert not list(tmp_path.iterdir())


def test_existing_export_is_preserved(tmp_path: Path) -> None:
    output = tmp_path / "private"
    output.mkdir()
    (output / "keep").write_text("synthetic")
    with pytest.raises(AdminError, match="already exists"):
        export_snapshots([], output)
    assert (output / "keep").read_text() == "synthetic"


def test_provider_is_part_of_image_identity(tmp_path: Path) -> None:
    first = member("caterpillar", "first")
    second = member("caterpillar", "second")
    second["source_provider"] = "another-synthetic-provider"
    summary = export_snapshots([first, second], tmp_path / "private")
    assert summary["unique_images"] == 2
    assert summary["categories"][0]["images"] == 2


def test_mixed_round_export_is_not_published(tmp_path: Path) -> None:
    first = member("caterpillar", "first")
    second = member("moth", "second")
    second["provenance"]["round_code"] = "OTHER-SYNTH"
    with pytest.raises(AdminError, match="different re-review rounds"):
        export_snapshots([first, second], tmp_path / "private")
    assert not list(tmp_path.iterdir())


def test_empty_round_does_not_publish_files(tmp_path: Path) -> None:
    with pytest.raises(AdminError, match="No published"):
        export_snapshots([], tmp_path / "private")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("unsafe", ["x'; drop table x;--", "../escape", "", "A" * 31])
def test_rejects_unsafe_round_identifiers(unsafe: str) -> None:
    for builder in (publication_sql, regroup_sql, snapshot_query):
        with pytest.raises(AdminError):
            builder(unsafe)


def test_category_paths_are_safe_and_collision_resistant() -> None:
    assert "/" not in category_filename("../../synthetic")
    assert category_filename("scientific_name:Papilio exemplaris") != category_filename(
        "scientific_name:Papilio-exemplaris"
    )
