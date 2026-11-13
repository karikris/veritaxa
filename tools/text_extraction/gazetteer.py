"""Local GeoNames token trie with canonical names and unresolved alternatives."""

import zipfile
from collections import defaultdict

from .common import tokens

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


COMMON.update(
    (
        "about after before above below across ag"
        "ain against almost alone along also alth"
        "ough always among amount and another any"
        " anyone anything anyway anywhere are aro"
        "und back became because become been behi"
        "nd being beside between both bottom but "
        "call cannot could did does doing done do"
        "wn due during each either else enough ev"
        "en ever every everyone everything everyw"
        "here except few first five four front fu"
        "ll further get give had has have hence h"
        "ere herself himself how however hundred "
        "indeed into itself just keep last least "
        "less made make many meanwhile might mine"
        " moreover most mostly much must myself n"
        "ame namely neither never next nine nobod"
        "y none nor nothing now nowhere off often"
        " once one only onto others otherwise our"
        " ours ourselves out over own part perhap"
        "s put quite rather really regarding same"
        " say see seem seemed seems serious sever"
        "al she should show side since six some s"
        "omehow someone something sometime somewh"
        "ere still such take taking taken than th"
        "at their them themselves then there ther"
        "efore these they third this those though"
        " three through throughout together too t"
        "op toward towards twelve twenty two unde"
        "r until upon used using various via was "
        "were what whatever when where whereas wh"
        "ether which while who whoever whole whom"
        " whose why with within without would yet"
        " yourself yourselves post posted posting"
        " add added level levels rainbow alley ha"
        "ll gold art award awards chance look see"
        "n area century wedding cake fruta norte "
        "south north east west sul sur noir blanc"
        " preta branco preto ici vous avec pour s"
        "ur que quando onde como muy canon nikon "
        "sony pentax olympus panasonic fujifilm s"
        "igma tamron eos dsc img def bug citrus f"
        "auna flora specimen specimens collection"
        " collections seen taking found visit inv"
        "ited group groups pool flickr views book"
        "mark favourite favorite favorites favour"
        "ites beautifulpicture sunsets sunset fri"
        "end friends comments comment count tell "
        "read reading reply certain regards aloha"
        " prompt hour hours minutes minute week w"
        "eeks year years month months abject sink"
    ).split()
)

COMMON.update(
    (
        "flor flores flore flower flowers cool am"
        "azing awesome commonwealth heliconia jul"
        "ia iulia dryas dingy barber trail road c"
        "hat detail details one two three single "
        "double triple faved fave faves score sco"
        "res challenge champions champion beautyf"
        "ul explore explored"
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


class Gazetteer:
    """Unicode token trie; retains geographic ambiguity instead of guessing a city."""

    def __init__(self, root):
        self.places, self.aliases, self.root, self.country_names = {}, defaultdict(set), {}, {}
        self.canonical_aliases = defaultdict(set)
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
            self.add_alias(name, gid, canonical=True)
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
                    self.add_alias(name, country_ids[code], canonical=True)
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
            self.add_alias(name, gid, canonical=True)
            self.add_alias(ascii_name, gid, canonical=True)
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
                    for name in [f[1], f[2]]:
                        self.add_alias(name, gid, canonical=True)
                    for name in f[3].split(","):
                        self.add_alias(name, gid)
        for alias, ids in self.aliases.items():
            node = self.root
            for word in alias:
                node = node.setdefault(word, {})
            node[None] = sorted(ids)

    def add_alias(self, name, gid, canonical=False):
        words = tuple(t[0] for t in tokens(name))
        if not words or len(words) > 12 or any(w.isdecimal() for w in words):
            return
        if " ".join(words) in GENERIC_PLACES:
            return
        if (
            len(words) == 1
            and self.places[gid]["level"] != "country"
            and (len(words[0]) < 4 or words[0] in COMMON)
        ):
            return
        self.aliases[words].add(gid)
        if canonical:
            self.canonical_aliases[words].add(gid)

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
