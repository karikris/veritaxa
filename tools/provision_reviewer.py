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


def normalise_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise AdminError("Provide a valid reviewer email address.")
    return email


def allowlist_reviewer(dsn: str, email: str) -> None:
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            update private.reviewer_allowlist
            set active = true
            where lower(email) = %s
            """,
            (email,),
        )
        if cursor.rowcount == 0:
            cursor.execute(
                """
                insert into private.reviewer_allowlist (email, active, created_by)
                values (%s, true, 'tools.provision_reviewer')
                """,
                (email,),
            )


def ensure_auth_user(project_url: str, secret_key: str, email: str) -> bool:
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
        if any(
            isinstance(user, dict)
            and isinstance(user.get("email"), str)
            and user["email"].lower() == email
            for user in users
        ):
            return False
        if len(users) < 1000:
            break
        page += 1

    _request_json(
        f"{base_url}/auth/v1/admin/users",
        headers,
        method="POST",
        body={"email": email, "email_confirm": True},
    )
    return True


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
    parser = argparse.ArgumentParser(description="Provision an approved VeriTaxa reviewer.")
    parser.add_argument("--email", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        email = normalise_email(args.email)
        allowlist_reviewer(database_url(), email)
        created = ensure_auth_user(
            supabase_project_url(),
            required_environment("SUPABASE_SECRET_KEY"),
            email,
        )
    except AdminError as error:
        if "Auth administration is unavailable" in str(error):
            print(
                "Allowlist updated, but Auth provisioning is unavailable. "
                "Create the supplied email in Supabase Authentication > Users, then rerun."
            )
        else:
            print("Reviewer provisioning failed. No email or credentials were printed.")
        return 1
    except psycopg.Error:
        print("Reviewer provisioning failed. No email or credentials were printed.")
        return 1

    state = "created" if created else "already existed"
    print(f"Reviewer provisioned: Auth user {state}; allowlist active.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
