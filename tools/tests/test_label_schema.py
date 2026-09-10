import json
from itertools import combinations
from pathlib import Path

import polars as pl

from tools.export_reviews import (
    DERIVED_LABELS,
    EXPECTED_RESULT_PRIORITY,
    LABEL_PRIORITY,
    SCHEMA_VERSION,
    add_derived_mappings,
    derived_mappings,
    summarize_votes,
)

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def read_schema(version):
    return json.loads((SCHEMAS / f"review-labels-v{version}.json").read_text())


def test_python_priority_matches_current_schema_and_retains_every_historical_label():
    current = read_schema(3)
    assert SCHEMA_VERSION == current["schemaVersion"]
    codes = tuple(
        label["code"] for label in sorted(current["labels"], key=lambda row: row["priority"])
    )
    # Legacy keyword decisions remain interpretable but rank after current codes.
    assert EXPECTED_RESULT_PRIORITY == (*codes, "flickr_keyword_match")
    historical = {
        label["code"] for version in (1, 2, 3) for label in read_schema(version)["labels"]
    }
    assert set(EXPECTED_RESULT_PRIORITY) == historical
    assert LABEL_PRIORITY == {
        code: position for position, code in enumerate(EXPECTED_RESULT_PRIORITY)
    }
    for higher, lower in combinations(EXPECTED_RESULT_PRIORITY, 2):
        assert summarize_votes({lower: 1, higher: 1}) == {
            "human_label": higher,
            "review_count": 2,
            "reviews_unanimous": False,
            "consensus_tied": True,
        }


def test_python_export_mappings_match_versioned_schema_including_legacy_keyword():
    current, legacy = read_schema(3)["mappings"], read_schema(2)["mappings"]
    expected = {
        "matches_flickr_keyword": set(legacy["flickrKeywordMatch"]),
        "matches_target_scientific_name": set(current["targetScientificName"]),
        "is_insecta_positive": set(current["insectaPositive"]),
        "is_lepidoptera_evidence": set(current["lepidopteraEvidence"]),
        "is_butterfly_positive": set(current["butterflyPositive"]),
        "is_butterfly_hard_negative": set(current["butterflyHardNegatives"]),
        "excluded_from_automatic_training": set(current["excludedFromAutomaticTraining"]),
    }
    assert list(DERIVED_LABELS) == list(expected)
    assert DERIVED_LABELS == expected
    for tied in (False, True):
        records = [
            {"human_label": label, "consensus_tied": tied}
            for label in (*EXPECTED_RESULT_PRIORITY, None, "unknown_future_label")
        ]
        eager = add_derived_mappings(pl.DataFrame(records)).select(list(expected)).to_dicts()
        streamed = [derived_mappings(record) for record in records]
        assert eager == streamed
        for record, derived in zip(records, streamed, strict=True):
            for column, labels in expected.items():
                value = None if record["human_label"] is None else record["human_label"] in labels
                if tied and column == "excluded_from_automatic_training":
                    value = True
                assert derived[column] == value
