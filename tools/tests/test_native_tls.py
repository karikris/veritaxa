"""Opt-in, real TLS tests against a disposable loopback fixture, never .env.admin."""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from benchmarks.export_database import synthetic_dsn
from tools.native_runtime import connect_admin, inspect_runtime, require_runtime
from tools.provision_reviewer import _request_json

pytestmark = pytest.mark.skipif(
    not os.environ.get("VERITAXA_TLS_TEST_DSN"), reason="explicit disposable TLS fixture required"
)


@pytest.fixture
def tls_dsn() -> str:
    value = synthetic_dsn(variable="VERITAXA_TLS_TEST_DSN")
    params = conninfo_to_dict(value)
    if params.get("sslmode") != "verify-full" or not params.get("sslrootcert"):
        pytest.fail("The disposable TLS fixture must explicitly verify its server certificate.")
    return value


@pytest.fixture
def certificate(tmp_path: Path) -> tuple[Path, Path]:
    cert, key = tmp_path / "server.crt", tmp_path / "server.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def test_actual_native_libraries_match_verified_source_manifest() -> None:
    require_runtime()
    manifest = json.loads(
        (Path(__file__).resolve().parents[2] / "admin/native-deps.json").read_text()
    )
    runtime = inspect_runtime()
    assert runtime.openssl == tuple(map(int, manifest["openssl"]["version"].split(".")))
    assert runtime.python_openssl == runtime.openssl
    major, minor = map(int, manifest["postgresql"]["version"].split("."))
    assert runtime.libpq == major * 10000 + minor


def test_verified_database_tls_preserves_copy_and_streaming(tls_dsn: str) -> None:
    with connect_admin(tls_dsn) as connection:
        assert connection.pgconn.ssl_in_use
        assert connection.execute(
            "select ssl from pg_stat_ssl where pid = pg_backend_pid()"
        ).fetchone() == (True,)
        connection.execute("create temporary table tls_synthetic (n integer, value text)")
        with connection.cursor() as cursor:
            with cursor.copy("copy tls_synthetic from stdin") as copy:
                for index in range(8):
                    copy.write_row((index, f"synthetic-{index}"))
            assert list(cursor.stream("select * from tls_synthetic order by n", size=1)) == [
                (index, f"synthetic-{index}") for index in range(8)
            ]


def test_database_certificate_verification_is_not_weakened(
    tls_dsn: str, certificate: tuple[Path, Path]
) -> None:
    unrelated_ca, _key = certificate
    wrong_ca_dsn = make_conninfo(tls_dsn, sslrootcert=str(unrelated_ca))
    with pytest.raises(psycopg.OperationalError, match="certificate verify failed"):
        connect_admin(wrong_ca_dsn)


def test_python_https_uses_the_patched_runtime(
    certificate: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    require_runtime()
    cert, key = certificate
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"users": []}')

        def log_message(self, _format: str, *args: object) -> None:
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert _request_json(f"https://127.0.0.1:{server.server_port}/", {}) == {"users": []}
        finally:
            server.shutdown()
            thread.join(timeout=5)
