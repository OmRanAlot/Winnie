"""Prepare a private category reference file; does not train or invoke a model."""

import argparse
import json
from pathlib import Path

from app.services.planning_history import read_taxonomy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calendar", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    taxonomy = read_taxonomy(args.calendar.read_text(encoding="utf-8-sig"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(taxonomy, output, indent=2)
    print(json.dumps({"examples": len(taxonomy["examples"]),
                      "categories": sorted({e["category"] for e in taxonomy["examples"]})}))


if __name__ == "__main__":
    main()
