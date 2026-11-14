"""Civil-day selection must respect the reviewer's timezone, including DST."""

from datetime import UTC, date, datetime, timedelta

import pytest

from tools.publish_latest_review_groups import review_window


def test_review_day_uses_local_midnight():
    assert review_window(date(2026, 11, 13), "Australia/Melbourne") == (
        datetime(2026, 11, 12, 13, tzinfo=UTC),
        datetime(2026, 11, 13, 13, tzinfo=UTC),
    )


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25)])
def test_review_day_respects_daylight_saving_changes(day, hours):
    start, end = review_window(day, "America/New_York")
    assert end - start == timedelta(hours=hours)
