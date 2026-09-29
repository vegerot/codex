#!/usr/bin/env python3
"""Host-local entry point for nightly run records and package operations."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.codex_package.nightly import (
    PROFILES,
    atomic_json,
    initialize,
    record_stage,
    status,
)


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
    restart = commands.add_parser("restart")
    restart.add_argument("--run-dir", type=Path, required=True)
    restart.add_argument("--worker", action="store_true")
    restart.add_argument("--check", action="store_true")
    source = commands.add_parser("source")
    source.add_argument("--run-dir", type=Path, required=True)
    source.add_argument("--commit", required=True)
    stage = commands.add_parser("record")
    stage.add_argument("--run-dir", type=Path, required=True)
    stage.add_argument("--stage", choices=("build", "publish"), required=True)
    stage.add_argument(
        "--status", choices=("success", "failed", "skipped"), required=True
    )
    stage.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        print(initialize(args.profile, args.coordinator))
    elif args.command == "source":
        import subprocess

        revision = subprocess.check_output(
            ["sl", "log", "--rev", args.commit, "--template", "{node}"], text=True
        ).strip()
        record = json.loads((args.run_dir / "run.json").read_text())
        if record["source_revision"] and record["source_revision"] != revision:
            parser.error("use a new run for a new source attempt")
        helpers = args.run_dir.resolve() / "helpers"
        if not helpers.exists():
            subprocess.run(
                [
                    "sl",
                    "--config",
                    "ui.archivemeta=false",
                    "archive",
                    "--type",
                    "files",
                    "--rev",
                    revision,
                    "--include",
                    "glob:scripts/**",
                    "--include",
                    "path:build.py",
                    str(helpers),
                ],
                check=True,
            )
        record.update(source_revision=revision, helper_revision=revision)
        atomic_json(args.run_dir / "run.json", record)
    elif args.command == "record":
        evidence = json.loads(args.evidence.read_text())
        record_stage(args.run_dir, args.stage, args.status, evidence=evidence)
    elif args.command == "restart":
        from scripts.codex_package.restart_nightly import finish, schedule

        result = (
            finish(args.run_dir.resolve(), args.check)
            if args.worker or args.check
            else schedule(args.run_dir.resolve())
        )
        print(json.dumps(result, indent=2))
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
            print("Live: " + json.dumps(result["live"]))
            for label in ("latest-attempt", "latest-verified"):
                record = result[label]
                print(f"{label}: {record['run_id'] if record else 'none recorded'}")
                if record:
                    for stage, evidence in record["stages"].items():
                        print(f"  {stage}: {evidence['status']}")


if __name__ == "__main__":
    main()
