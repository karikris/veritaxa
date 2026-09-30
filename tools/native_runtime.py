"""Prove the admin client's loaded TLS runtime before opening a connection."""

from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict

from tools.common import AdminError

RECOVERY = (
    "Admin TLS runtime is unsafe or unverified. "
    "Use the patched admin image documented in README.md, "
    "or run python -m tools.native_runtime after updating the native libraries."
)


class NativeRuntimeError(AdminError):
    """A credential-free native-runtime failure safe to display to an operator."""


@dataclass(frozen=True)
class NativeRuntime:
    implementation: str
    libpq: int
    openssl: tuple[int, int, int]
    python_openssl: tuple[int, int, int]
    verified: bool


class _DlInfo(ctypes.Structure):
    _fields_ = [
        ("filename", ctypes.c_char_p),
        ("base", ctypes.c_void_p),
        ("symbol", ctypes.c_char_p),
        ("address", ctypes.c_void_p),
    ]


def _symbol_path(function: Any) -> Path:
    dladdr = ctypes.CDLL(None).dladdr
    dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DlInfo)]
    dladdr.restype = ctypes.c_int
    info = _DlInfo()
    if not dladdr(ctypes.cast(function, ctypes.c_void_p), ctypes.byref(info)) or not info.filename:
        raise NativeRuntimeError(RECOVERY)
    return Path(os.fsdecode(info.filename)).resolve(strict=True)


def _loaded_providers() -> dict[str, set[Path]]:
    providers: dict[str, set[Path]] = {"libpq": set(), "libssl": set(), "libcrypto": set()}
    for line in Path("/proc/self/maps").read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6 or not fields[5].startswith("/"):
            continue
        path = Path(fields[5])
        match = re.match(r"^(libpq|libssl|libcrypto)(?:[.-]|$)", path.name)
        if match:
            providers[match[1]].add(path.resolve(strict=True))
    return providers


def inspect_runtime() -> NativeRuntime:
    """Linux dynamic linkage only; unknown/static/ambiguous runtimes fail closed.

    Resolve symbols through the selected Psycopg extension's dependency scope.
    A second mapped provider makes symbol interposition ambiguous, so neither a
    system version nor a different loaded OpenSSL can be mistaken for libpq's.
    """
    try:
        if sys.platform != "linux" or psycopg.pq.__impl__ != "c":
            raise NativeRuntimeError(RECOVERY)
        extension = importlib.import_module("psycopg_c.pq")
        library = ctypes.CDLL(extension.__file__)
        pq_version = library.PQlibVersion
        pq_version.argtypes = []
        pq_version.restype = ctypes.c_int
        crypto_version = library.OpenSSL_version_num
        crypto_version.argtypes = []
        crypto_version.restype = ctypes.c_ulong
        number = crypto_version()
        openssl = (number >> 28, (number >> 20) & 0xFF, (number >> 4) & 0xFF)
        python_library = ctypes.CDLL(importlib.import_module("_ssl").__file__)
        python_crypto_version = python_library.OpenSSL_version_num
        python_crypto_version.argtypes = []
        python_crypto_version.restype = ctypes.c_ulong
        python_number = python_crypto_version()
        python_openssl = (
            python_number >> 28,
            (python_number >> 20) & 0xFF,
            (python_number >> 4) & 0xFF,
        )
        providers = _loaded_providers()
        verified = (
            providers["libpq"] == {_symbol_path(pq_version)}
            and providers["libssl"] == {_symbol_path(library.SSL_new)}
            and providers["libcrypto"] == {_symbol_path(crypto_version)}
            and _symbol_path(python_library.SSL_new) == _symbol_path(library.SSL_new)
            and _symbol_path(python_crypto_version) == _symbol_path(crypto_version)
            and pq_version() == psycopg.pq.version()
        )
        return NativeRuntime(
            implementation=psycopg.pq.__impl__,
            libpq=psycopg.pq.version(),
            openssl=openssl,
            python_openssl=python_openssl,
            verified=verified,
        )
    except (OSError, AttributeError, ImportError, ValueError) as error:
        raise NativeRuntimeError(RECOVERY) from error


def validate_runtime(runtime: NativeRuntime) -> None:
    # Only reviewed release lines are accepted. A newer major/minor is not
    # automatically safe: 3.6.0, for example, is newer than vulnerable 3.5.8.
    if (
        not runtime.verified
        or runtime.implementation != "c"
        or not 180006 <= runtime.libpq < 190000
        or runtime.openssl[:2] != (3, 5)
        or runtime.openssl[2] < 9
        or runtime.python_openssl != runtime.openssl
    ):
        raise NativeRuntimeError(RECOVERY)


def require_runtime() -> None:
    validate_runtime(inspect_runtime())


def _local_plaintext_fixture(dsn: str) -> bool:
    """The only exemption is explicit plaintext on a named disposable fixture.

    No DNS, Unix sockets, service files, hostaddr, multi-host strings or PG*
    environment defaults can redirect this exception to a remote connection.
    Local TLS still parses certificates and is never exempted.
    """
    if any(name.startswith("PG") for name in os.environ):
        return False
    try:
        params = conninfo_to_dict(dsn)
    except psycopg.Error:
        return False
    return (
        set(params).issubset(
            {
                "host",
                "port",
                "dbname",
                "user",
                "password",
                "sslmode",
                "gssencmode",
                "connect_timeout",
                "application_name",
            }
        )
        and params.get("host") in {"127.0.0.1", "::1"}
        and params.get("dbname") in {"veritaxa_synthetic", "veritaxa_import_synthetic"}
        and params.get("sslmode") == "disable"
        and params.get("gssencmode") == "disable"
        and params.get("port", "5432").isascii()
        and params.get("port", "5432").isdigit()
        and 1 <= int(params.get("port", "5432")) <= 65535
    )


def connect_admin(dsn: str) -> psycopg.Connection[Any]:
    if not _local_plaintext_fixture(dsn):
        require_runtime()
    return psycopg.connect(dsn)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="Print credential-free version evidence"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {"safe": False}
    try:
        runtime = inspect_runtime()
        report.update(asdict(runtime))
        validate_runtime(runtime)
        report["safe"] = True
    except NativeRuntimeError:
        report["error"] = RECOVERY
    if args.json:
        print(json.dumps(report))
    else:
        print(json.dumps(report, indent=2))
    return 0 if report["safe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
