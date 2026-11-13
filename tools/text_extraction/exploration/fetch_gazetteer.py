"""Download public GeoNames inputs once, retaining checksums and attribution."""

import argparse
from pathlib import Path
from urllib.request import Request, urlopen

from ..common import digest, dump

FILES = ("cities1000.zip", "countryInfo.txt", "admin1CodesASCII.txt")
SOURCE = "https://download.geonames.org/export/dump/"


def fetch(destination):
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {"source": SOURCE, "license": "CC BY 4.0", "files": {}}
    for name in FILES:
        path = destination / name
        if not path.exists():
            request = Request(
                SOURCE + name, headers={"User-Agent": "Veritaxa geolocation research"}
            )
            temporary = path.with_suffix(path.suffix + ".tmp")
            with urlopen(request, timeout=60) as response, temporary.open("wb") as file:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise ValueError("Gazetteer download exceeds the bounded input size")
                    file.write(chunk)
            temporary.replace(path)
        manifest["files"][name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(dump(fetch(args.output)))


if __name__ == "__main__":
    main()
