from __future__ import annotations

from typing import Any

import pytest

from tools.common import AdminError
from tools.provision_reviewer import main, normalise_email


def test_normalises_email_without_placing_it_in_source_configuration() -> None:
    assert normalise_email("  Reviewer@Example.INVALID ") == "reviewer@example.invalid"
    with pytest.raises(AdminError):
        normalise_email("not-an-email")


def test_success_output_does_not_print_reviewer_email(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr("tools.provision_reviewer.database_url", lambda: "postgres" + "ql://unused")
    monkeypatch.setattr("tools.provision_reviewer.allowlist_reviewer", lambda *_args: None)
    monkeypatch.setattr(
        "tools.provision_reviewer.required_environment", lambda name: f"synthetic-{name}"
    )
    monkeypatch.setattr("tools.provision_reviewer.ensure_auth_user", lambda *_args: True)

    result = main(["--email", "reviewer@example.invalid"])
    output = capsys.readouterr().out

    assert result == 0
    assert "reviewer@example.invalid" not in output
    assert "Auth user created" in output
