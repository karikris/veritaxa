from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg

from tools.common import (
    AdminError,
    database_url,
    required_environment,
    supabase_project_url,
    validate_https_url,
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_IDENTIFIED_BY_LENGTH = 100


def normalise_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise AdminError("Provide a valid reviewer email address.")
    return email


def normalise_identified_by(value: str) -> str:
    identified_by = value.strip()
    if not identified_by or len(identified_by) > MAX_IDENTIFIED_BY_LENGTH:
        raise AdminError("Provide an identified-by value between 1 and 100 characters.")
    return identified_by


def activate_reviewer_profile(dsn: str, user_id: str, email: str, identified_by: str) -> None:
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            update private.reviewer_profiles
            set active = true, email = %s, identified_by = %s
            where user_id = %s::uuid
            """,
            (email, identified_by, user_id),
        )
        if cursor.rowcount != 1:
            raise AdminError("The Auth user does not have a reviewer profile.")


def ensure_auth_user(
    project_url: str, secret_key: str, email: str, identified_by: str
) -> tuple[bool, str]:
    base_url = validate_https_url(project_url, "SUPABASE_URL").rstrip("/")
    headers = {
        "apikey": secret_key,
        "authorization": f"Bearer {secret_key}",
        "content-type": "application/json",
    }
    page = 1
    while page <= 100:
        query = urlencode({"page": page, "per_page": 1000})
        payload = _request_json(f"{base_url}/auth/v1/admin/users?{query}", headers)
        users = payload.get("users")
        if not isinstance(users, list):
            raise AdminError("Supabase Auth returned an invalid user list.")
        for user in users:
            if (
                isinstance(user, dict)
                and isinstance(user.get("email"), str)
                and user["email"].lower() == email
                and isinstance(user.get("id"), str)
            ):
                return (False, user["id"])
        if len(users) < 1000:
            break
        page += 1

    created_user = _request_json(
        f"{base_url}/auth/v1/admin/users",
        headers,
        method="POST",
        body={
            "email": email,
            "email_confirm": True,
            "user_metadata": {"identified_by": identified_by},
        },
    )
    user_id = created_user.get("id")
    if not isinstance(user_id, str):
        raise AdminError("Supabase Auth returned an invalid created user.")
    return (True, user_id)


def _request_json(
    url: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, headers=headers, method=method, data=data)
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise AdminError("Supabase Auth administration is unavailable.") from error
    if not isinstance(payload, dict):
        raise AdminError("Supabase Auth returned an invalid response.")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administratively provision a VeriTaxa reviewer.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--identified-by", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        email = normalise_email(args.email)
        identified_by = normalise_identified_by(args.identified_by)
        created, user_id = ensure_auth_user(
            supabase_project_url(),
            required_environment("SUPABASE_SECRET_KEY"),
            email,
            identified_by,
        )
        activate_reviewer_profile(database_url(), user_id, email, identified_by)
    except AdminError as error:
        if "Auth administration is unavailable" in str(error):
            print(
                "Auth provisioning is unavailable. "
                "The reviewer can register through the public VeriTaxa form instead."
            )
        else:
            print("Reviewer provisioning failed. No email or credentials were printed.")
        return 1
    except psycopg.Error:
        print("Reviewer provisioning failed. No email or credentials were printed.")
        return 1

    state = "created" if created else "already existed"
    print(f"Reviewer provisioned: Auth user {state}; profile active.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
