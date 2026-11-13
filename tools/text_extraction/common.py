"""Stable serialization, fingerprints, Unicode tokens and source excerpts."""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

TOKEN = re.compile(r"[\u3400-\u9fff]|[^\W_\u3400-\u9fff]+", re.UNICODE)


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


def snippet(text, start, end, context=140):
    return text[max(0, start - context) : min(len(text), end + context)].strip()
