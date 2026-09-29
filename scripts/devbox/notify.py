#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets==15.0.1"]
# ///
"""Load the announcement task, then enqueue a report without interrupting it."""

import argparse
import asyncio
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.codex_package.rpc import notify


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--thread", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--message")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    asyncio.run(notify(args.thread, args.message, args.check))
