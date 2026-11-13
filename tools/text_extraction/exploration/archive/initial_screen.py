"""Historical broad-screen diagnostic; its matches are unsuitable for location assignment.

The default sample is 1,000 images. Use a fresh output directory. This preserved
prototype exposes the filename, dictionary and broad-context failure modes that
motivated the main library. It makes no Flickr API calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sqlite3
import unicodedata
import zipfile
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import polars as pl

TOKEN = re.compile(r"[\u3400-\u9fff]|[^\W_\u3400-\u9fff]+", re.UNICODE)
COMMON = set(
    (
        "a an the at in on of to for from by as i"
        "s it me my you your us all can will may "
        "nice great good love lovely beautiful am"
        "azing wonderful fantastic stunning excel"
        "lent awesome happy thanks thank congratu"
        "lations bravo wow superb macro butterfly"
        " butterflies insect insects nature garde"
        "n gardens animal animals male female adu"
        "lt larva larvae moth eggs pupa caterpill"
        "ar lemon lime red blue green yellow blac"
        "k white orange common small large best n"
        "ew old wild flower leaf plant spring sum"
        "mer winter autumn march june july august"
        " day night time light water home family "
        "friend world rose pink silver golden vie"
        "w close click photo photos photography p"
        "hotograph image pictures shot capture co"
        "mposition sharp beauty perfect super del"
        "icious peace queen king prince princess "
        "bluebird cricket welcome please very wel"
        "l more other indian indianlimebutterfly "
        "papilio demoleus polytes china?"
    ).split()
)
GENERIC_PLACES = {
    "national park",
    "nature reserve",
    "nature park",
    "botanical garden",
    "botanical gardens",
    "butterfly park",
    "butterfly garden",
    "butterfly gardens",
}
CAPTURE = re.compile(
    (
        "\\b(?:taken|photographed|captured|photogr"
        "aphing|spotted|sighted|observed|seen|fou"
        "nd|shot|visited|visiting|walking|hiking|"
        "feeding|perched)\\s+(?:\\w+\\s+){0,5}(?:in|"
        "at|near|outside|around|along|on)\\b|\\b(?:"
        "location|locality|撮影地|拍攝地|拍摄地)\\s*[:\uff1a]|\\b"
        "(?:national park|nature reserve|botanica"
        "l garden|butterfly park)\\b"
    ),
    re.I,
)
DISTRIBUTION = re.compile(
    (
        "\\b(?:native to|distribution|distributed|"
        "range extends|ranges from|found througho"
        "ut|widespread|occurs throughout|introduc"
        "ed to|species is found|endemic to)\\b"
    ),
    re.I,
)
SPECIES_RANGE = re.compile(
    (
        "\\b(?:species|genus|family|plant)\\s+(?:(?"
        ":is|are|can be|may be)\\s+)?(?:found|occu"
        "rs?|occurring|grows?)\\b"
    ),
    re.I,
)
CAPTURE_PREFIX = re.compile(
    (
        "\\b(?:taken|photographed|captured|spotted"
        "|sighted|observed|seen|found|shot|visite"
        "d|visiting|feeding|perched)\\s+(?:[\\w'-]+"
        "\\s+){0,4}(?:in|at|near|outside|around|al"
        "ong)\\s+(?:[\\w'-]+[\\s,]+){0,4}$|\\b(?:loca"
        "tion|locality)\\s*[:\uff1a]\\s*$"
    ),
    re.I,
)
GREETING = re.compile(
    (
        "\\b(?:greetings? from|regards? from|hello"
        " from|cheers from|welcome to|invited to|"
        "post (?:it |this )?to|add (?:it |this )?"
        "to|our group|join (?:us|the group)|flick"
        "r group)\\b"
    ),
    re.I,
)
QUESTION = re.compile(
    (
        "\\b(?:where|which (?:country|place|park|c"
        "ity)|is this (?:in|at)|was this (?:in|at"
        "|taken))\\b"
    ),
    re.I,
)
RELATIVE = re.compile(
    (
        "\\b(?:(?:half (?:an? )?|quarter (?:of an?"
        " )?)(?:hour)|(?P<number>an?|one|two|thre"
        "e|four|five|six|twelve|twenty[- ]four|\\d"
        "+(?:\\.\\d+)?)\\s+(?P<unit>hours?|hrs?|minu"
        "tes?|mins?|days?|weeks?))\\s+(?P<directio"
        "n>before|prior(?: to)?|earlier|later|aft"
        "er|ago)\\b"
    ),
    re.I,
)
CLOCK = re.compile(
    (
        "\\b(?:at|around|about|by)\\s+(?:around\\s+)"
        "?(\\d{1,2}[:.]\\d{2}\\s*(?:a\\.?m\\.?|p\\.?m\\."
        "?))\\b"
    ),
    re.I,
)
LOCALITY = re.compile(
    (
        "\\b(?:taken|photographed|captured|spotted"
        "|sighted|observed|seen|found|shot|visite"
        "d|feeding|perched)\\s+(?:\\w+\\s+){0,3}(?:i"
        "n|at|near|outside|around|along)\\s+([^\\n."
        "!?]{3,180})|\\b(?:location|locality)\\s*[:"
        "\uff1a]\\s*([^\\n.!?]{3,180})"
    ),
    re.I,
)
COORD_TAG = re.compile(
    (
        "(?:geo:|geotagged:)?(lat(?:itude)?|lon(?"
        ":gitude)?|lng)\\s*[=:]\\s*[\\\"']?(-?\\d+(?:\\"
        ".\\d+)?)"
    ),
    re.I,
)
COORD_TEXT = re.compile(
    (
        "\\b(?:latitude|lat)\\s*[:=]\\s*(-?\\d{1,2}(?"
        ":\\.\\d+)?)\\s*[,; /]+\\s*(?:longitude|lon|l"
        "ng)\\s*[:=]\\s*(-?\\d{1,3}(?:\\.\\d+)?)"
    ),
    re.I,
)


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def tokens(text):
    return [
        (unicodedata.normalize("NFKC", m.group()).casefold(), m.start(), m.end())
        for m in TOKEN.finditer(text)
    ]


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.hidden = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li"}:
            self.parts.append("\n")
        if tag == "a":
            self.links.extend(v for k, v in attrs if k == "href" and v)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


def visible(raw):
    parser = VisibleText()
    parser.feed(str(raw or ""))
    return re.sub(r"[ \t]+", " ", "".join(parser.parts)).strip(), parser.links


def valid_coordinates(latitude, longitude):
    try:
        a, b = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if (
        not all(map(math.isfinite, (a, b)))
        or not (-90 <= a <= 90 and -180 <= b <= 180)
        or (a == 0 and b == 0)
    ):
        return None
    return a, b


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


class Gazetteer:
    """Unicode token trie; retains geographic ambiguity instead of guessing a city."""

    def __init__(self, root):
        self.places, self.aliases, self.root, self.country_names = {}, defaultdict(set), {}, {}
        country_ids = {}
        for line in (root / "countryInfo.txt").read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 17:
                continue
            code, name, gid = fields[0], fields[4], fields[16]
            self.country_names[code] = name
            country_ids[code] = gid
            self.places[gid] = dict(
                geoname_id=gid,
                name=name,
                level="country",
                country=code,
                country_name=name,
                latitude=None,
                longitude=None,
                population=int(fields[7] or 0),
                admin1=None,
            )
            self.add_alias(name, gid)
        aliases = {
            "US": ["United States", "United States of America", "USA", "U.S.A."],
            "GB": ["United Kingdom", "UK", "Great Britain"],
            "AE": ["United Arab Emirates", "UAE"],
            "KR": ["South Korea"],
            "KP": ["North Korea"],
            "TW": ["Taiwan"],
            "VN": ["Vietnam", "Viet Nam"],
            "LA": ["Laos"],
            "RU": ["Russia"],
            "CZ": ["Czechia", "Czech Republic"],
        }
        for code, names in aliases.items():
            if code in country_ids:
                for name in names:
                    self.add_alias(name, country_ids[code])
        for line in (root / "admin1CodesASCII.txt").read_text().splitlines():
            fields = line.split("\t")
            if len(fields) < 4:
                continue
            code, name, ascii_name, gid = fields
            country, admin = code.split(".", 1)
            self.places[gid] = dict(
                geoname_id=gid,
                name=name,
                level="region",
                country=country,
                country_name=self.country_names.get(country),
                latitude=None,
                longitude=None,
                population=0,
                admin1=admin,
            )
            self.add_alias(name, gid)
            self.add_alias(ascii_name, gid)
        with zipfile.ZipFile(root / "cities1000.zip") as archive:
            import io

            with io.TextIOWrapper(archive.open("cities1000.txt"), encoding="utf-8") as file:
                for line in file:
                    f = line.rstrip("\n").split("\t")
                    gid = f[0]
                    self.places[gid] = dict(
                        geoname_id=gid,
                        name=f[1],
                        level="settlement",
                        country=f[8],
                        country_name=self.country_names.get(f[8]),
                        admin1=f[10],
                        latitude=float(f[4]),
                        longitude=float(f[5]),
                        population=int(f[14]),
                    )
                    for name in [f[1], f[2], *f[3].split(",")]:
                        self.add_alias(name, gid)
        for alias, ids in self.aliases.items():
            node = self.root
            for word in alias:
                node = node.setdefault(word, {})
            node[None] = sorted(ids)

    def add_alias(self, name, gid):
        words = tuple(t[0] for t in tokens(name))
        if not words or len(words) > 12 or any(w.isdecimal() for w in words):
            return
        if (
            len(words) == 1
            and self.places[gid]["level"] != "country"
            and (len(words[0]) < 3 or words[0] in COMMON)
        ):
            return
        self.aliases[words].add(gid)

    def find(self, text):
        words, i = tokens(text), 0
        while i < len(words):
            node, j, matches = self.root, i, []
            while j < len(words) and words[j][0] in node:
                node = node[words[j][0]]
                j += 1
                if None in node:
                    matches.append((j, node[None]))
            if matches:
                end, ids = matches[-1]
                yield words[i][1], words[end - 1][2], ids
                i = end
            else:
                i += 1


def snippet(text, start, end, context=140):
    return text[max(0, start - context) : min(len(text), end + context)].strip()


def units(row):
    owner = (
        json.loads(row.get("flickr_current_owner_json") or "{}").get("nsid")
        or row.get("owner_id")
        or ""
    )
    emitted = set()
    for source, fields in [
        ("title", ["flickr_current_title", "raw_title"]),
        ("description", ["flickr_current_description", "raw_description"]),
    ]:
        for field in fields:
            value, links = visible(row.get(field))
            if value and (source, value) not in emitted:
                emitted.add((source, value))
                yield dict(
                    source=source,
                    field=field,
                    text=value,
                    links=links,
                    author_is_owner=True,
                    comment_id=None,
                    comment_author=None,
                    comment_created_at=None,
                )
    tags = json.loads(row.get("flickr_current_tags_json") or "{}").get("tag", [])
    values = [t.get("raw") or t.get("_content") or "" for t in tags] + str(
        row.get("raw_tags") or ""
    ).split()
    for raw in dict.fromkeys(values):
        value, links = visible(raw)
        if value:
            yield dict(
                source="tag",
                field="flickr_current_tags_json/raw_tags",
                text=value,
                links=links,
                author_is_owner=True,
                comment_id=None,
                comment_author=None,
                comment_created_at=None,
            )
    for comment in json.loads(row.get("flickr_comments_json") or "[]"):
        value, links = visible(comment.get("_content"))
        if value:
            yield dict(
                source="comment",
                field="flickr_comments_json",
                text=value,
                links=links,
                author_is_owner=comment.get("author") == owner,
                comment_id=comment.get("id"),
                comment_author=comment.get("author"),
                comment_created_at=comment.get("datecreate"),
            )
    profile = json.loads(row.get("flickr_current_owner_json") or "{}").get("location")
    if profile:
        yield dict(
            source="owner_profile",
            field="flickr_current_owner_json.location",
            text=str(profile),
            links=[],
            author_is_owner=True,
            comment_id=None,
            comment_author=None,
            comment_created_at=None,
        )


def relative_clues(unit):
    found = []
    for match in RELATIVE.finditer(unit["text"]):
        raw, number = match.group(), match.group("number")
        if raw.lower().startswith("half"):
            amount, scale = 0.5, "hour"
        elif raw.lower().startswith("quarter"):
            amount, scale = 0.25, "hour"
        else:
            value = {
                "a": 1,
                "an": 1,
                "one": 1,
                "two": 2,
                "three": 3,
                "four": 4,
                "five": 5,
                "six": 6,
                "twelve": 12,
                "twenty-four": 24,
                "twenty four": 24,
            }.get(number.lower())
            amount = float(number) if value is None else value
            scale = match.group("unit").lower()
        multiplier = (
            60
            if scale.startswith(("h", "hr"))
            else 1
            if scale.startswith(("m", "min"))
            else 1440
            if scale.startswith("day")
            else 10080
        )
        direction = match.group("direction").lower()
        reference = (
            "comment_narrative_reference_unresolved"
            if unit["source"] == "comment"
            else "photo_narrative_reference_unresolved"
        )
        context = snippet(unit["text"], match.start(), match.end())
        if re.search(r"\b(?:pupae?|chrysalis|emerg\w*|hatch\w*|larva\w*)\b", context, re.I):
            narrative = "biological_stage_timing"
        elif GREETING.search(context):
            narrative = "group_or_greeting_timing"
        elif re.search(
            (
                "\\b(?:arriv\\w*|depart\\w*|driv\\w*|travel\\w"
                "*|walk\\w*|bus|train|breakfast|hotel|hike"
                "|journey)\\b"
            ),
            context,
            re.I,
        ):
            narrative = "travel_or_itinerary_timing"
        else:
            narrative = "relative_time_unspecified"
        found.append(
            dict(
                expression=raw,
                minutes=amount * multiplier,
                direction="before"
                if direction.startswith(("before", "prior", "earlier", "ago"))
                else "after",
                reference_basis=reference,
                narrative_type=narrative,
                excerpt=context,
            )
        )
    return found


def evidence_for_unit(unit, gazetteer, tag_countries):
    text, results = unit["text"], []
    matched = list(gazetteer.find(text))
    local_countries = {
        gazetteer.places[gid]["country"]
        for _, _, ids in matched
        for gid in ids
        if gazetteer.places[gid]["level"] == "country"
    }
    for start, end, ids in matched:
        matched_text = text[start:end]
        context = snippet(text, start, end)
        capture, distribution = bool(CAPTURE.search(context)), bool(DISTRIBUTION.search(context))
        greeting, question = (
            bool(GREETING.search(context)),
            bool(QUESTION.search(context) and "?" in context),
        )
        places = [gazetteer.places[gid] for gid in ids]
        # Unstructured lowercase city homonyms are too noisy without a capture cue.
        if (
            unit["source"] not in ("tag", "owner_profile")
            and not capture
            and matched_text.islower()
            and not any(p["level"] == "country" for p in places)
        ):
            continue
        countries = local_countries or tag_countries
        resolved = (
            [p for p in places if p["country"] in countries] if len(countries) == 1 else places
        )
        if not resolved:
            resolved = places
        country_places = [p for p in resolved if p["level"] == "country"]
        if country_places and len({p["country"] for p in resolved}) == 1:
            resolved = country_places
        flags = []
        if distribution:
            flags.append("biogeographic_distribution_context")
        if greeting:
            flags.append("greeting_or_group_context")
        if question:
            flags.append("location_question_not_assertion")
        if unit["source"] == "owner_profile":
            flags.append("owner_home_not_photo_location")
        if unit["source"] == "comment" and not unit["author_is_owner"]:
            flags.append("third_party_comment")
        if len(resolved) > 1:
            flags.append("ambiguous_place_name")
        if any(p["level"] == "settlement" for p in resolved):
            flags.append("gazetteer_center_not_photo_coordinate")
        explicit = capture and not (distribution or greeting or question)
        exact_tag = unit["source"] == "tag" and text.strip(' #"') == matched_text
        location_tag = unit["source"] == "tag" and bool(
            re.match(r"geo(?:country|region|city)|(?:geo:)?(?:country|region|city)\s*=", text, re.I)
        )
        if unit["source"] == "owner_profile":
            kind = "owner_profile_place"
        elif question:
            kind = "location_question"
        elif greeting:
            kind = "greeting_or_group_place"
        elif distribution:
            kind = "distribution_place"
        elif unit["source"] == "comment":
            kind = (
                "owner_comment_locality"
                if explicit and unit["author_is_owner"]
                else "third_party_comment_locality"
                if explicit
                else "comment_place_mention"
            )
        elif explicit:
            kind = "explicit_photo_locality"
        elif exact_tag or location_tag:
            kind = "place_tag"
        elif unit["source"] == "title":
            kind = "title_place"
        else:
            kind = "description_place_mention"
        eligible = (
            kind
            in {"explicit_photo_locality", "place_tag", "title_place", "owner_comment_locality"}
            and len(resolved) == 1
        )
        results.append(
            dict(
                kind=kind,
                matched_text=matched_text,
                excerpt=context,
                candidates=resolved,
                candidate_count=len(resolved),
                flags=flags,
                capture_locality_candidate=eligible,
            )
        )
    return results


def coordinate_tags(row):
    tags = json.loads(row.get("flickr_current_tags_json") or "{}").get("tag", [])
    value = "\n".join(
        [str(row.get(k) or "") for k in ["machine_tags", "raw_tags"]]
        + [str(t.get("raw") or t.get("_content") or "") for t in tags]
    )
    pairs = defaultdict(set)
    for match in COORD_TAG.finditer(value):
        pairs["lat" if match[1].lower().startswith("lat") else "lon"].add(float(match[2]))
    if len(pairs["lat"]) == len(pairs["lon"]) == 1:
        return valid_coordinates(next(iter(pairs["lat"])), next(iter(pairs["lon"])))
    return None


def source_locations(cache_path, ids):
    connection = sqlite3.connect(f"file:{Path(cache_path).resolve()}?mode=ro", uri=True)
    result, snapshots = {}, []
    try:
        for pid, status, payload, retrieved in connection.execute(
            "SELECT photo_id,status,payload,retrieved_at FROM responses WHERE endpoint='info'"
        ):
            if pid not in ids:
                continue
            location = (
                json.loads(payload).get("photo", {}).get("location") if status == "ok" else None
            )
            snapshots.append(
                dict(
                    flickr_photo_id=pid,
                    status=status,
                    retrieved_at=retrieved,
                    provider_location_json=dump(location) if location else None,
                )
            )
            if location and (
                coordinates := valid_coordinates(
                    location.get("latitude"), location.get("longitude")
                )
            ):
                result[pid] = dict(
                    latitude=coordinates[0],
                    longitude=coordinates[1],
                    location=location,
                    retrieved_at=retrieved,
                )
    finally:
        connection.close()
    return result, snapshots


def safe_frame(records):
    return pl.DataFrame(
        [{k: dump(v) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in records],
        infer_schema_length=None,
    )


def snapshot(path, destination):
    if not destination.exists():
        shutil.copyfile(path, destination)
    if digest(path) != digest(destination):
        raise ValueError(f"Input changed since snapshot: {path}; choose a new output directory")
    return pl.read_parquet(destination)


def analyse(source, geotagged_source, cache_path, gazetteer_root, output, limit=1000):
    output.mkdir(parents=True, exist_ok=True)
    source_frame = snapshot(source, output / "input_original.parquet")
    geo_frame = snapshot(geotagged_source, output / "input_geotagged.parquet")
    if source_frame["flickr_photo_id"].n_unique() != source_frame.height:
        raise ValueError("Duplicate original photo IDs")
    rows, geo_rows = (
        (source_frame.head(limit) if limit else source_frame).to_dicts(),
        geo_frame.to_dicts(),
    )
    geo_ids = {str(r["flickr_photo_id"]) for r in geo_rows}
    ids = {str(r["flickr_photo_id"]) for r in rows}
    public, cache_snapshot = source_locations(cache_path, ids)
    safe_frame(cache_snapshot).write_parquet(output / "provider_location_snapshot.parquet")
    gazetteer = Gazetteer(gazetteer_root)
    print(
        dump(
            {
                "state": "gazetteer_loaded",
                "places": len(gazetteer.places),
                "aliases": len(gazetteer.aliases),
            }
        ),
        flush=True,
    )
    anchors, seen = defaultdict(list), set()
    for row in geo_rows + rows:
        pid = str(row["flickr_photo_id"])
        coordinates = public.get(pid)
        method = "flickr_getInfo_location"
        if not coordinates:
            point = (
                valid_coordinates(row.get("latitude"), row.get("longitude"))
                if pid in geo_ids
                else None
            )
            coordinates = dict(latitude=point[0], longitude=point[1]) if point else None
            method = "flickr_search_geotag"
        if not coordinates:
            point = coordinate_tags(row)
            coordinates = dict(latitude=point[0], longitude=point[1]) if point else None
            method = "explicit_coordinate_machine_tags"
        date, _quality = capture_time(row)
        owner = json.loads(row.get("flickr_current_owner_json") or "{}").get("nsid") or row.get(
            "owner_id"
        )
        if coordinates and date and owner and pid not in seen:
            anchors[owner].append(
                dict(
                    photo_id=pid,
                    date=date,
                    latitude=coordinates["latitude"],
                    longitude=coordinates["longitude"],
                    method=method,
                    page_url=row.get("photo_page_url"),
                    coordinate_accuracy=row.get("geolocation_accuracy_flickr_level"),
                )
            )
            seen.add(pid)
    evidence, relative, temporal, summaries = [], [], [], []
    methods = Counter()
    for index, row in enumerate(rows):
        pid = str(row["flickr_photo_id"])
        owner = json.loads(row.get("flickr_current_owner_json") or "{}").get("nsid") or row.get(
            "owner_id"
        )
        photo_units = list(units(row))
        tag_countries = set()
        for unit in photo_units:
            if unit["source"] != "tag":
                continue
            for _, _, matches in gazetteer.find(unit["text"]):
                tag_countries.update(
                    gazetteer.places[i]["country"]
                    for i in matches
                    if gazetteer.places[i]["level"] == "country"
                )
        photo_evidence, photo_relative = [], []
        for unit in photo_units:
            common = {k: v for k, v in unit.items() if k not in {"text", "links"}}
            for clue in evidence_for_unit(unit, gazetteer, tag_countries):
                photo_evidence.append(dict(flickr_photo_id=pid, **common, **clue))
            if unit["source"] != "owner_profile":
                for clue in relative_clues(unit):
                    photo_relative.append(dict(flickr_photo_id=pid, **common, **clue))
                for match in CLOCK.finditer(unit["text"]):
                    photo_relative.append(
                        dict(
                            flickr_photo_id=pid,
                            **common,
                            expression=match[0],
                            minutes=None,
                            direction=None,
                            reference_basis="clock_time_in_text_timezone_unresolved",
                            excerpt=snippet(unit["text"], match.start(), match.end()),
                        )
                    )
                if not list(gazetteer.find(unit["text"])):
                    for match in LOCALITY.finditer(unit["text"]):
                        photo_evidence.append(
                            dict(
                                flickr_photo_id=pid,
                                **common,
                                kind="unresolved_locality_phrase",
                                matched_text=match[1] or match[2],
                                excerpt=snippet(unit["text"], match.start(), match.end()),
                                candidates=[],
                                candidate_count=0,
                                flags=["uncatalogued_locality_requires_review"],
                                capture_locality_candidate=False,
                            )
                        )
                for match in COORD_TEXT.finditer(unit["text"]):
                    point = valid_coordinates(match[1], match[2])
                    if point:
                        photo_evidence.append(
                            dict(
                                flickr_photo_id=pid,
                                **common,
                                kind="coordinate_pair_in_text",
                                matched_text=match[0],
                                excerpt=snippet(unit["text"], match.start(), match.end()),
                                candidates=[dict(latitude=point[0], longitude=point[1])],
                                candidate_count=1,
                                flags=["text_coordinate_reference_requires_review"],
                                capture_locality_candidate=False,
                            )
                        )
        neighbors, time_quality = temporal_neighbors(row, anchors.get(owner, []))
        photo_temporal = []
        for anchor in neighbors:
            photo_temporal.append(
                dict(
                    flickr_photo_id=pid,
                    owner_id=owner,
                    target_capture_time=json.loads(
                        row.get("flickr_current_dates_json") or "{}"
                    ).get("taken"),
                    anchor_flickr_photo_id=anchor["photo_id"],
                    anchor_capture_time=anchor["date"].isoformat(sep=" "),
                    anchor_photo_page_url=anchor["page_url"],
                    anchor_latitude=anchor["latitude"],
                    anchor_longitude=anchor["longitude"],
                    anchor_method=anchor["method"],
                    anchor_coordinate_accuracy=anchor["coordinate_accuracy"],
                    minutes_anchor_before_target=anchor["minutes_before_target"],
                    relation=anchor["relation"],
                    time_window=anchor["time_window"],
                    matching_anchor_count=anchor["matching_anchor_count"],
                    time_basis=time_quality,
                    inference_status="temporal_location_clue_only_target_coordinate_unassigned",
                )
            )
        machine = coordinate_tags(row)
        candidates = [e for e in photo_evidence if e["capture_locality_candidate"]]
        hour = [n for n in photo_temporal if n["time_window"] == "within_1_hour"]
        photo_text = [
            e
            for e in photo_evidence
            if e["source"] not in {"owner_profile"}
            and e["kind"]
            not in {"greeting_or_group_place", "distribution_place", "location_question"}
        ]
        if pid in public:
            status = "public_flickr_coordinates_recovered"
        elif machine:
            status = "coordinate_machine_tags_require_review"
        elif candidates:
            status = "named_capture_locality_candidate"
        elif hour:
            status = "same_owner_geotagged_neighbor_within_1_hour"
        elif photo_text:
            status = "text_location_clues_require_review"
        elif photo_temporal:
            status = "same_owner_geotagged_neighbor_within_24_hours"
        elif photo_relative:
            status = "relative_time_clue_only"
        elif any(e["source"] == "owner_profile" for e in photo_evidence):
            status = "owner_profile_only_not_photo_location"
        else:
            status = "no_supported_location_clue_found"
        methods[status] += 1
        unique_places = {
            p.get("geoname_id"): p
            for e in candidates
            for p in e["candidates"]
            if p.get("geoname_id")
        }
        summaries.append(
            dict(
                flickr_photo_id=pid,
                photo_page_url=row.get("photo_page_url"),
                owner_id=owner,
                title=row.get("flickr_current_title") or row.get("raw_title"),
                capture_time=json.loads(row.get("flickr_current_dates_json") or "{}").get("taken"),
                capture_time_quality=time_quality,
                has_saved_human_review=row.get("has_saved_review"),
                human_majority_label=row.get("first_round_strict_majority_result"),
                location_clue_status=status,
                provider_latitude=public.get(pid, {}).get("latitude"),
                provider_longitude=public.get(pid, {}).get("longitude"),
                coordinate_machine_tags_json=dict(latitude=machine[0], longitude=machine[1])
                if machine
                else None,
                named_locality_candidates_json=list(unique_places.values()),
                location_evidence_count=len(photo_evidence),
                photo_text_location_evidence_count=len(photo_text),
                owner_comment_location_evidence_count=sum(
                    e["source"] == "comment" and e["author_is_owner"] for e in photo_evidence
                ),
                third_party_comment_location_evidence_count=sum(
                    e["source"] == "comment" and not e["author_is_owner"] for e in photo_evidence
                ),
                owner_profile_location=json.loads(row.get("flickr_current_owner_json") or "{}").get(
                    "location"
                ),
                relative_time_clue_count=len(photo_relative),
                geotagged_neighbors_within_1_hour=len(hour),
                geotagged_neighbor_before_within_1_hour=any(
                    n["relation"] == "earlier" for n in hour
                ),
                geotagged_neighbor_after_within_1_hour=any(n["relation"] == "later" for n in hour),
                closest_geotagged_neighbor_json=min(
                    photo_temporal, key=lambda n: abs(n["minutes_anchor_before_target"])
                )
                if photo_temporal
                else None,
                inferred_target_latitude=None,
                inferred_target_longitude=None,
                review_status="location_not_independently_verified",
            )
        )
        evidence.extend(photo_evidence)
        relative.extend(photo_relative)
        temporal.extend(photo_temporal)
        if (index + 1) % 1000 == 0:
            print(
                dump(
                    {
                        "processed": index + 1,
                        "total": len(rows),
                        "location_evidence": len(evidence),
                        "temporal_links": len(temporal),
                    }
                ),
                flush=True,
            )
    for name, records in [
        ("image_geolocation_clues", summaries),
        ("location_evidence", evidence),
        ("relative_time_evidence", relative),
        ("temporal_geotagged_neighbors", temporal),
    ]:
        frame = safe_frame(records)
        frame.write_parquet(output / f"{name}.parquet")
        frame.write_csv(output / f"{name}.csv")
    summary = dict(
        total_images=len(rows),
        cached_comments_checked=sum(
            len(json.loads(r.get("flickr_comments_json") or "[]")) for r in rows
        ),
        public_coordinate_images=len(public),
        machine_coordinate_images=sum(bool(r["coordinate_machine_tags_json"]) for r in summaries),
        images_with_named_capture_locality_candidate=sum(
            bool(r["named_locality_candidates_json"]) for r in summaries
        ),
        images_with_photo_text_place_clue=sum(
            r["photo_text_location_evidence_count"] > 0 for r in summaries
        ),
        images_with_owner_comment_place_clue=sum(
            r["owner_comment_location_evidence_count"] > 0 for r in summaries
        ),
        images_with_third_party_comment_place_clue=sum(
            r["third_party_comment_location_evidence_count"] > 0 for r in summaries
        ),
        images_with_relative_time_clue=sum(r["relative_time_clue_count"] > 0 for r in summaries),
        images_with_geotagged_neighbor_within_1_hour=sum(
            r["geotagged_neighbors_within_1_hour"] > 0 for r in summaries
        ),
        images_with_geotagged_neighbor_before_within_1_hour=sum(
            r["geotagged_neighbor_before_within_1_hour"] for r in summaries
        ),
        images_with_geotagged_neighbor_after_within_1_hour=sum(
            r["geotagged_neighbor_after_within_1_hour"] for r in summaries
        ),
        images_with_geotagged_neighbor_within_24_hours=sum(
            r["closest_geotagged_neighbor_json"] is not None for r in summaries
        ),
        mutually_exclusive_status_counts=dict(methods),
        evidence_rows=len(evidence),
        relative_time_rows=len(relative),
        temporal_link_rows=len(temporal),
        geotagged_anchor_images=sum(map(len, anchors.values())),
        flickr_api_calls=0,
    )
    manifest = dict(
        created_at_utc=datetime.now(UTC).isoformat(),
        summary=summary,
        source_sha256={
            str(p): digest(p)
            for p in [
                output / "input_original.parquet",
                output / "input_geotagged.parquet",
                output / "provider_location_snapshot.parquet",
            ]
        },
        gazetteer_sha256={p.name: digest(p) for p in gazetteer_root.iterdir() if p.is_file()},
        code_sha256=digest(Path(__file__)),
        gazetteer_source="https://download.geonames.org/export/dump/",
        gazetteer_license="CC BY 4.0",
        limitations=[
            (
                "Gazetteer matching is candidate extracti"
                "on, not a trained contextual geocoder. A"
                "mbiguous place names remain unresolved."
            ),
            (
                "Cities under 1000 population and landmar"
                "ks may be absent. Named-place centers ar"
                "e not image coordinates."
            ),
            (
                "Comments can describe the commenter or s"
                "pecies range rather than the photo. Owne"
                "r profile locations are not capture loca"
                "tions."
            ),
            (
                "Recorded same-owner wall-clock times hav"
                "e no verified timezone. Unknown, coarse,"
                " midnight and timezone-aware capture tim"
                "es are excluded from temporal matching."
            ),
            (
                "A geotagged photo taken an hour earlier "
                "or later is a clue, not a location or un"
                "certainty bound for this photo."
            ),
            (
                "No other photos outside the supplied col"
                "lections were fetched. No bulk geocoding"
                " API or Flickr API used."
            ),
            "Inferred target coordinates remain empty pending source/context review.",
        ],
    )
    (output / "analysis_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(dump(summary), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--geotagged-source", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--gazetteer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--limit", type=int, default=1000, help="Diagnostic image limit; 0 scans all source images"
    )
    args = parser.parse_args()
    if (args.output / "analysis_manifest.json").exists():
        parser.error("Historical probe requires a fresh output directory")
    analyse(args.source, args.geotagged_source, args.cache, args.gazetteer, args.output, args.limit)


if __name__ == "__main__":
    main()
