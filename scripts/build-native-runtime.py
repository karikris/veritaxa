"""Build the admin TLS dependencies from pinned, checksum-verified upstream sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen


def build(prefix: Path, jobs: int) -> None:
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "admin/native-deps.json").read_text()
    )
    prefix = prefix.resolve()
    prefix.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="veritaxa-native-build-") as directory:
        root = Path(directory)
        sources = {}
        for name, package in manifest.items():
            archive = root / f"{name}.tar"
            digest = hashlib.sha256()
            with urlopen(package["url"], timeout=60) as response, archive.open("wb") as output:
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    output.write(block)
            if digest.hexdigest() != package["sha256"]:
                raise RuntimeError(f"Checksum mismatch for {name}; nothing will be built.")
            destination = root / name
            destination.mkdir()
            with tarfile.open(archive) as source:
                source.extractall(destination, filter="data")
            sources[name] = next(destination.iterdir())

        environment = {
            **os.environ,
            "PATH": f"{prefix}/bin:{os.environ['PATH']}",
            "LD_LIBRARY_PATH": str(prefix / "lib"),
            "CPPFLAGS": f"-I{prefix}/include",
            "LDFLAGS": f"-L{prefix}/lib -Wl,-rpath,{prefix}/lib",
            "PKG_CONFIG_PATH": str(prefix / "lib/pkgconfig"),
        }

        def run(arguments: list[str], cwd: Path) -> None:
            subprocess.run(arguments, cwd=cwd, env=environment, check=True)

        openssl = sources["openssl"]
        run(
            [
                "./Configure",
                "shared",
                "no-tests",
                f"--prefix={prefix}",
                "--libdir=lib",
                "--openssldir=/etc/ssl",
            ],
            openssl,
        )
        run(["make", f"-j{jobs}"], openssl)
        run(["make", "install_sw"], openssl)
        postgres = sources["postgresql"]
        run(
            [
                "./configure",
                f"--prefix={prefix}",
                "--with-openssl",
                "--without-readline",
                "--without-zlib",
                "--without-icu",
            ],
            postgres,
        )
        run(["make", f"-j{jobs}", "-C", "src/interfaces/libpq"], postgres)
        run(["make", "-C", "src/interfaces/libpq", "install"], postgres)
        run(["make", "-C", "src/bin/pg_config", "install"], postgres)
        run(["make", "-C", "src/include", "install"], postgres)
        (prefix / "native-deps.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path("/opt/veritaxa-native"))
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    build(args.prefix, args.jobs)
