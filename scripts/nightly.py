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
    verify = commands.add_parser("verify")
    verify.add_argument("--profile", choices=PROFILES, required=True)
    verify.add_argument("--run-dir", type=Path, required=True)
    verify.add_argument("--package", type=Path, required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("--profile", choices=PROFILES, required=True)
    activate.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        print(initialize(args.profile, args.coordinator))
    elif args.command == "activate":
        from scripts.codex_package.activation import activate_verified

        if (
            json.loads((args.run_dir / "run.json").read_text())["profile"]
            != args.profile
        ):
            parser.error("profile differs from run")
        print(json.dumps(activate_verified(args.run_dir), indent=2))
    elif args.command == "verify":
        from scripts.codex_package.verify_nightly import verify_run

        record = json.loads((args.run_dir / "run.json").read_text())
        if record["profile"] != args.profile:
            parser.error("profile differs from run")
        print(json.dumps(verify_run(args.run_dir, args.package), indent=2))
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
