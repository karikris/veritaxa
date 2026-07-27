from __future__ import annotations

from typing import Any

import pytest

from tools.common import AdminError, supabase_project_url
from tools.provision_reviewer import main, normalise_email, normalise_identified_by


def test_normalises_email_without_placing_it_in_source_configuration() -> None:
    assert normalise_email("  Reviewer@Example.INVALID ") == "reviewer@example.invalid"
    with pytest.raises(AdminError):
        normalise_email("not-an-email")


def test_normalises_identified_by() -> None:
    assert normalise_identified_by("  Synthetic reviewer  ") == "Synthetic reviewer"
    with pytest.raises(AdminError):
        normalise_identified_by("   ")
    with pytest.raises(AdminError):
        normalise_identified_by("x" * 101)


def test_success_output_does_not_print_reviewer_email(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr("tools.provision_reviewer.database_url", lambda: "postgres" + "ql://unused")
    monkeypatch.setattr("tools.provision_reviewer.allowlist_reviewer", lambda *_args: None)
    monkeypatch.setattr(
        "tools.provision_reviewer.supabase_project_url",
        lambda: "https://synthetic-project.example.invalid",
    )
    monkeypatch.setattr(
        "tools.provision_reviewer.required_environment", lambda name: f"synthetic-{name}"
    )
    monkeypatch.setattr("tools.provision_reviewer.ensure_auth_user", lambda *_args: True)

    result = main(
        [
            "--email",
            "reviewer@example.invalid",
            "--identified-by",
            "Synthetic reviewer",
        ]
    )
    output = capsys.readouterr().out

    assert result == 0
    assert "reviewer@example.invalid" not in output
    assert "Auth user created" in output


def test_project_url_falls_back_to_jwks_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.common.load_admin_environment", lambda: None)
    monkeypatch.delenv("VERITAXA_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PROJECT_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "sb_publishable_synthetic")
    monkeypatch.setenv(
        "SUPABASE_JWKS_URL",
        "https://synthetic-project.example.invalid/auth/v1/.well-known/jwks.json",
    )

    assert supabase_project_url() == "https://synthetic-project.example.invalid"


def test_project_url_rejects_api_key_without_valid_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tools.common.load_admin_environment", lambda: None)
    monkeypatch.delenv("VERITAXA_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PROJECT_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "sb_publishable_synthetic")
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)

    with pytest.raises(AdminError, match="Supabase project HTTPS origin"):
        supabase_project_url()
