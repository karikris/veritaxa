"""Same-owner wall-clock neighbor evidence without interpolated coordinates."""

import json
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime


def capture_time(row):
    dates = json.loads(row.get("flickr_current_dates_json") or "{}")
    if str(dates.get("takenunknown")) != "0" or str(dates.get("takengranularity")) != "0":
        return None, "unknown_or_coarse_capture_time"
    try:
        date = datetime.fromisoformat(dates.get("taken", ""))
    except (TypeError, ValueError):
        return None, "missing_or_invalid_capture_time"
    if date.tzinfo is not None:
        return None, "mixed_timezone_basis_requires_review"
    if (date.hour, date.minute, date.second) == (0, 0, 0):
        return None, "midnight_capture_time_requires_review"
    return date, "same_owner_recorded_wall_clock_timezone_unverified"


def temporal_neighbors(target, anchors, hours=24):
    date, quality = capture_time(target)
    if date is None:
        return [], quality
    candidates = sorted(
        (a for a in anchors if a["photo_id"] != str(target["flickr_photo_id"])),
        key=lambda a: a["date"],
    )
    dates = [a["date"] for a in candidates]
    from datetime import timedelta

    lo = bisect_left(dates, date - timedelta(hours=hours))
    hi = bisect_right(dates, date + timedelta(hours=hours))
    groups = defaultdict(list)
    for anchor in candidates[lo:hi]:
        seconds = (date - anchor["date"]).total_seconds()
        relation = "earlier" if seconds > 0 else "later" if seconds < 0 else "same_time"
        bucket = "within_1_hour" if abs(seconds) <= 3600 else "within_24_hours"
        groups[bucket, relation].append(
            dict(anchor, minutes_before_target=seconds / 60, relation=relation, time_window=bucket)
        )
    # Closest anchor per direction and window; all matching counts are retained.
    selected = []
    for group in groups.values():
        best = min(group, key=lambda a: (abs(a["minutes_before_target"]), a["photo_id"]))
        selected.append(dict(best, matching_anchor_count=len(group)))
    return selected, quality
