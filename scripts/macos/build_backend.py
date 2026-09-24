#!/usr/bin/env python3
"""Select SCM only when both internal build services route through a VPN tunnel."""

import json
import re
import subprocess


def select_backend(route_outputs):
    interfaces = [
        match.group(1)
        if (match := re.search(r"^\s*interface:\s*(\S+)", output, re.M))
        else None
        for output in route_outputs
    ]
    return {
        "backend": "scm"
        if all(interface and interface.startswith("utun") for interface in interfaces)
        else "local",
        "interfaces": interfaces,
    }


def main():
    hosts = ("code.byted.org", "cloud.bytedance.net")
    outputs = []
    for host in hosts:
        try:
            result = subprocess.run(
                ["/sbin/route", "-n", "get", host],
                capture_output=True,
                text=True,
                timeout=10,
            )
            outputs.append(result.stdout if result.returncode == 0 else "")
        except subprocess.TimeoutExpired:
            outputs.append("")
    print(json.dumps({"hosts": hosts, **select_backend(outputs)}))


if __name__ == "__main__":
    main()
