#!/usr/bin/env python3
"""Host-local entry point for nightly run records and package operations."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.codex_package.nightly import PROFILES, initialize, status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--profile", choices=PROFILES, required=True)
    init.add_argument("--coordinator", type=Path)
    show = commands.add_parser("status")
    show.add_argument("--profile", choices=PROFILES, required=True)
    show.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "init":
        print(initialize(args.profile, args.coordinator))
    else:
        result = status(args.profile)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Codex nightly: {args.profile}")
            for label in ("latest-attempt", "latest-verified"):
                record = result[label]
                print(f"{label}: {record['run_id'] if record else 'none recorded'}")
                if record:
                    for stage, evidence in record["stages"].items():
                        print(f"  {stage}: {evidence['status']}")


if __name__ == "__main__":
    main()
