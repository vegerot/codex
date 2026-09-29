"""Versioned, host-local records for independent nightly stages."""

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROFILES = ("macos", "devbox", "debian", "windows")
STAGES = ("build", "verify", "activate", "publish", "restart")
ROOT = Path(__file__).resolve().parents[2]


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    os.replace(temporary, path)


def state_root(profile):
    return Path.home() / ".local/state/codex-nightly" / profile


def initialize(profile, coordinator=None, state=None):
    state = state or state_root(profile)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run = state / "runs" / stamp
    run.mkdir(parents=True)
    revision = subprocess.check_output(
        ["sl", "log", "--rev", ".", "--template", "{node}"], cwd=ROOT, text=True
    ).strip()
    instructions = ROOT / "scripts/nightly"
    shutil.copy2(instructions / "workflow.md", run / "workflow.md")
    shutil.copy2(instructions / "profiles" / f"{profile}.md", run / "profile.md")
    if coordinator:
        shutil.copy2(coordinator, run / "coordinator.md")
    (run / "prompt.md").write_text(
        "Execute this run's saved workflow.md and profile.md. Save report.md here.\n"
    )
    record = {
        "schema_version": 1,
        "run_id": stamp,
        "profile": profile,
        "instruction_revision": revision,
        "source_revision": None,
        "helper_revision": None,
        "stages": {stage: {"status": "pending"} for stage in STAGES},
    }
    if profile == "windows":
        for stage in ("activate", "restart"):
            record["stages"][stage] = {"status": "not_requested"}
    atomic_json(run / "run.json", record)
    atomic_json(state / "latest-attempt.json", {"run_dir": str(run)})
    return run


def record_stage(run, stage, status, **evidence):
    record = json.loads((run / "run.json").read_text())
    record["stages"][stage] = {"status": status, **evidence}
    atomic_json(run / "run.json", record)
    if stage == "verify" and status == "success":
        atomic_json(run.parents[1] / "latest-verified.json", {"run_dir": str(run)})
    return record


def status(profile, state=None):
    state = state or state_root(profile)
    result = {"profile": profile}
    for label in ("latest-attempt", "latest-verified"):
        pointer = state / f"{label}.json"
        result[label] = (
            json.loads(
                (
                    Path(json.loads(pointer.read_text())["run_dir"]) / "run.json"
                ).read_text()
            )
            if pointer.exists()
            else None
        )
    if profile == "windows":
        result["live"] = {"activation": "not_requested"}
    else:
        cli = Path.home() / ".local/bin/codex"
        try:
            info = json.loads(
                subprocess.check_output(
                    [str(cli), "app-server", "daemon", "version"], text=True, timeout=30
                )
            )
            result["live"] = {"cli": str(cli.resolve()), **info}
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            result["live"] = {"error": str(error)}
    return result
