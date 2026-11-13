"""Command-line interface for the reusable location-clue pipeline."""

import argparse
from pathlib import Path

from .pipeline import analyse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--geotagged-source", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--gazetteer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyse(args.source, args.geotagged_source, args.cache, args.gazetteer, args.output)
