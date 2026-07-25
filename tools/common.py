from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit


class AdminError(Exception):
    """Expected validation or configuration failure safe to show to an operator."""


def load_admin_environment(path: Path = Path(".env.admin")) -> None:
    """Load a simple local dotenv file without overriding the process environment."""
    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise AdminError(f"Invalid .env.admin entry on line {line_number}.")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        if not key.isidentifier():
            raise AdminError(f"Invalid .env.admin variable on line {line_number}.")
        os.environ.setdefault(key, value)


def database_url() -> str:
    load_admin_environment()
    for name in (
        "VERITAXA_DATABASE_URL",
        "SUPABASE_DB_URL",
        "DATABASE_URL",
        "BIOMINER_WORKSTORE_DSN",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise AdminError(
        "Set VERITAXA_DATABASE_URL in .env.admin or provide a supported database URL variable."
    )


def required_environment(name: str) -> str:
    load_admin_environment()
    value = os.environ.get(name, "").strip()
    if not value:
        raise AdminError(f"Set {name} in .env.admin or the process environment.")
    return value


def validate_https_url(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AdminError(f"{field} must be an HTTPS URL.")
    candidate = value.strip()
    if not candidate or len(candidate) > 2048:
        raise AdminError(f"{field} must be an HTTPS URL no longer than 2048 characters.")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in candidate)
    ):
        raise AdminError(f"{field} must be a credential-free HTTPS URL.")
    return candidate


def optional_https_url(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    return validate_https_url(value, field)
