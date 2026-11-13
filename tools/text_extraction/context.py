"""Source-aware place, country-context and relative-time candidate extraction."""

import re

from .common import snippet, tokens

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


BIO_DESCRIPTION = re.compile(
    (
        "\\b(?:species|genus|family|native|widespr"
        "ead|distributed|distribution|habitat|mig"
        "ration|migrant|medium[- ]sized|pierid|re"
        "maining few species)\\b"
    ),
    re.I,
)


PHOTO_ASSERTION = re.compile(
    (
        "\\b(?:(?:this|my|the)\\s+(?:photo|photogra"
        "ph|image|picture|shot)|I\\s+(?:saw|found|"
        "photographed|spotted|took)|we\\s+(?:saw|f"
        "ound|photographed|spotted))\\b"
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


def country_context(photo_units, gazetteer):
    """Use other place labels to resolve homonyms; never self-confirm Georgia."""
    direct, sets, forced = set(), [], set()
    for unit in photo_units:
        if unit["source"] not in {"tag", "title"}:
            continue
        for start, end, ids in gazetteer.find(unit["text"]):
            key = tuple(w[0] for w in tokens(unit["text"][start:end]))
            canonical = gazetteer.canonical_aliases.get(key, set())
            places = [gazetteer.places[i] for i in ids if i in canonical]
            countries = {p["country"] for p in places}
            if not countries:
                continue
            if countries:
                sets.append(countries)
            country_places = [p for p in places if p["level"] == "country"]
            if country_places and len(countries) == 1:
                direct.update(countries)
            if unit["source"] == "tag" and re.match(r"geo:country=", unit["text"], re.I):
                forced.update(p["country"] for p in country_places)
    if forced:
        return forced
    if direct:
        return direct
    intersection = set.intersection(*sets) if len(sets) >= 2 else set()
    return intersection if len(intersection) == 1 else set()


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
    local_countries = set()
    for start, end, ids in matched:
        canonical = gazetteer.canonical_aliases.get(
            tuple(w[0] for w in tokens(text[start:end])), set()
        )
        places = [gazetteer.places[i] for i in ids if i in canonical]
        if len({p["country"] for p in places}) == 1:
            local_countries.update(p["country"] for p in places if p["level"] == "country")
    for start, end, ids in matched:
        matched_text = text[start:end]
        context = snippet(text, start, end)
        capture = bool(CAPTURE_PREFIX.search(text[max(0, start - 150) : start]))
        distribution = bool(
            DISTRIBUTION.search(context)
            or SPECIES_RANGE.search(context)
            or (BIO_DESCRIPTION.search(context) and not PHOTO_ASSERTION.search(context))
        )
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
        countries = tag_countries or local_countries
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
        if unit["source"] == "tag" and unit["author_is_owner"] is not True:
            flags.append("tag_author_not_verified_as_owner")
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
        if eligible and resolved[0]["level"] == "settlement" and not countries and not explicit:
            eligible = False
            flags.append("settlement_lacks_country_or_capture_context")
        canonical = tuple(w[0] for w in tokens(matched_text))
        if (
            eligible
            and resolved[0]["level"] == "settlement"
            and resolved[0]["geoname_id"] not in gazetteer.canonical_aliases.get(canonical, set())
            and not explicit
        ):
            eligible = False
            flags.append("alternate_settlement_name_without_capture_context")
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
