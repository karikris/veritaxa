from __future__ import annotations

import os
from dataclasses import replace
from unittest.mock import Mock

import pytest

from tools import native_runtime as native

SAFE = native.NativeRuntime("c", 180006, (3, 5, 9), (3, 5, 9), True)
LOCAL = "host=127.0.0.1 dbname=veritaxa_synthetic sslmode=disable gssencmode=disable"


@pytest.fixture(autouse=True)
def clear_pg_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.startswith("PG"):
            monkeypatch.delenv(name)


@pytest.mark.parametrize(
    "runtime",
    [
        replace(SAFE, openssl=(3, 5, 8)),
        replace(SAFE, openssl=(3, 6, 0), python_openssl=(3, 6, 0)),
        replace(SAFE, openssl=(4, 0, 3), python_openssl=(4, 0, 3)),
        replace(SAFE, python_openssl=(3, 0, 16)),
        replace(SAFE, libpq=180005),
        replace(SAFE, libpq=190000),
        replace(SAFE, implementation="binary"),
        replace(SAFE, verified=False),
    ],
)
def test_unreviewed_or_ambiguous_runtime_is_rejected(runtime: native.NativeRuntime) -> None:
    with pytest.raises(native.NativeRuntimeError):
        native.validate_runtime(runtime)


def test_reviewed_runtime_is_accepted() -> None:
    native.validate_runtime(SAFE)


@pytest.mark.parametrize(
    "dsn",
    [
        "host=database.example.invalid dbname=veritaxa_synthetic sslmode=disable",
        LOCAL.replace("127.0.0.1", "localhost"),
        LOCAL.replace("127.0.0.1", "127.0.0.1,database.example.invalid"),
        LOCAL.replace("127.0.0.1", "/tmp/veritaxa-postgres-test"),
        LOCAL.replace("sslmode=disable", "sslmode=require"),
        LOCAL.replace("veritaxa_synthetic", "real_database"),
        LOCAL + " hostaddr=198.51.100.1",
        LOCAL + " service=synthetic",
        LOCAL + " port=5432,5433",
        "dbname=veritaxa_synthetic sslmode=disable gssencmode=disable",
    ],
)
def test_unsafe_runtime_blocks_before_connect_even_when_tls_disabled(
    monkeypatch: pytest.MonkeyPatch, dsn: str
) -> None:
    connect = Mock()
    monkeypatch.setattr(native.psycopg, "connect", connect)
    monkeypatch.setattr(native, "inspect_runtime", lambda: replace(SAFE, openssl=(3, 5, 8)))
    with pytest.raises(native.NativeRuntimeError):
        native.connect_admin(dsn)
    connect.assert_not_called()


@pytest.mark.parametrize("name", ["PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_connection_environment_cannot_redirect_fixture_exception(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "untrusted-default")
    assert not native._local_plaintext_fixture(LOCAL)


def test_local_explicit_plaintext_fixture_does_not_use_tls_inspector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect = Mock(side_effect=native.NativeRuntimeError(native.RECOVERY))
    connect = Mock()
    monkeypatch.setattr(native, "inspect_runtime", inspect)
    monkeypatch.setattr(native.psycopg, "connect", connect)
    native.connect_admin(LOCAL)
    inspect.assert_not_called()
    connect.assert_called_once_with(LOCAL)


def test_safe_remote_connection_keeps_existing_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native, "inspect_runtime", lambda: SAFE)
    connect = Mock()
    monkeypatch.setattr(native.psycopg, "connect", connect)
    dsn = "host=database.example.invalid sslmode=verify-full connect_timeout=20"
    native.connect_admin(dsn)
    connect.assert_called_once_with(dsn)


def test_provider_ambiguity_is_detected_from_actual_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        native.Path,
        "read_text",
        lambda _path: (
            "1-2 r-xp 0000 00:00 1 /opt/libssl.so.3\n"
            "3-4 r-xp 0000 00:00 1 /opt/libssl.so.3\n"
            "5-6 r-xp 0000 00:00 2 /other/libssl-bundled.so.3\n"
        ),
    )
    monkeypatch.setattr(native.Path, "resolve", lambda path, **_kwargs: path)
    assert len(native._loaded_providers()["libssl"]) == 2


def test_non_linux_and_binary_implementations_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native.sys, "platform", "darwin")
    with pytest.raises(native.NativeRuntimeError):
        native.inspect_runtime()


def test_http_provisioning_refuses_unsafe_runtime_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = Mock()
    monkeypatch.setattr("tools.provision_reviewer.urlopen", request)
    monkeypatch.setattr(native, "inspect_runtime", lambda: replace(SAFE, openssl=(3, 5, 8)))
    from tools.provision_reviewer import _request_json

    with pytest.raises(native.NativeRuntimeError):
        _request_json("https://synthetic.example.invalid", {})
    request.assert_not_called()
