"""Select the source CLI and its separate daemon; leave desktop packages alone."""

import asyncio
import ctypes
import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def lock_file(path):
    import msvcrt

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def powershell(script, **variables):
    return subprocess.check_output(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference = 'Stop'; " + script,
        ],
        env={**os.environ, **variables},
        text=True,
    )


def junction(link, target):
    powershell(
        "New-Item -ItemType Junction -Path $env:NIGHTLY_LINK -Target $env:NIGHTLY_TARGET -Force | Out-Null",
        NIGHTLY_LINK=str(link),
        NIGHTLY_TARGET=str(target),
    )


def ensure_user_path(launchers):
    powershell(
        "$p = [Environment]::GetEnvironmentVariable('Path','User'); "
        "$parts = @($p -split ';' | Where-Object { $_ -and $_.TrimEnd('\\') -ine $env:NIGHTLY_BIN.TrimEnd('\\') }); "
        "[Environment]::SetEnvironmentVariable('Path', ($env:NIGHTLY_BIN + ';' + ($parts -join ';')), 'User'); "
        "Add-Type '[System.Runtime.InteropServices.DllImport(\"user32.dll\", CharSet=System.Runtime.InteropServices.CharSet.Unicode)] public static extern System.IntPtr SendMessageTimeout(System.IntPtr h, uint m, System.UIntPtr w, string l, uint f, uint t, out System.UIntPtr r);' -Name NightlyEnvironment -Namespace Native; "
        "$r = [UIntPtr]::Zero; [Native.NightlyEnvironment]::SendMessageTimeout([IntPtr]0xffff, 0x1a, [UIntPtr]::Zero, 'Environment', 2, 1000, [ref]$r) | Out-Null",
        NIGHTLY_BIN=str(launchers),
    )


def activate(run):
    from scripts.codex_package.nightly import record_stage
    from scripts.codex_package.verify_nightly import hashes

    record = json.loads((run / "run.json").read_text())
    verified = record["stages"]["verify"]
    if verified["status"] != "success":
        raise RuntimeError("Activation requires successful package verification")
    package = Path(verified["package"]).resolve()
    if hashes(package) != verified["hashes"]:
        raise RuntimeError("Package changed after verification")
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    daemon = home / "packages/app-server-daemon/current"
    current = Path.home() / ".local/share/codex-windows-build/current"
    launchers = Path.home() / ".local/bin"
    launcher = launchers / "codex.cmd"
    if (
        launcher.exists()
        and "rem Codex Windows nightly CLI" not in launcher.read_text()
    ):
        raise RuntimeError(f"Refusing to overwrite unmanaged launcher: {launcher}")
    previous = {
        str(p): str(p.resolve()) if p.exists() else None for p in (current, daemon)
    }
    with lock_file(daemon.parent / "install.lock"):
        junction(daemon, package)
        junction(current, package)
        launchers.mkdir(parents=True, exist_ok=True)
        launcher.write_text(
            "\n".join(
                (
                    "@echo off",
                    "rem Codex Windows nightly CLI",
                    f'"{current / "bin/codex.exe"}" %*',
                    "exit /b %errorlevel%",
                    "",
                )
            ),
            encoding="utf-8",
            newline="\r\n",
        )
        ensure_user_path(launchers)
    record_stage(
        run,
        "activate",
        "success",
        package=str(package),
        previous=previous,
        launcher=str(launcher),
    )
    record_stage(run, "restart", "pending", package=str(package))
    return {"package": str(package), "launcher": str(launcher), "restart": "pending"}


def connect_socket(path, uri):
    # CPython on Windows omits AF_UNIX even though Windows supports it.
    from websockets.sync.client import unix_connect

    winsock = ctypes.WinDLL("Ws2_32.dll")
    winsock.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    winsock.socket.restype = ctypes.c_size_t
    winsock.connect.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int]

    class Address(ctypes.Structure):
        _fields_ = [("family", ctypes.c_ushort), ("path", ctypes.c_char * 108)]

    handle = winsock.socket(1, socket.SOCK_STREAM, 0)
    connection = socket.socket(family=1, type=socket.SOCK_STREAM, fileno=handle)
    address = Address(1, str(path).encode("utf-8"))
    if winsock.connect(handle, ctypes.byref(address), ctypes.sizeof(address)) != 0:
        connection.close()
        raise OSError(winsock.WSAGetLastError(), f"Cannot connect to {path}")
    return unix_connect(
        sock=connection, uri=uri, compression=None, max_size=8 * 1024 * 1024
    )


def process_identity(pid):
    return json.loads(
        powershell(
            "$p = Get-Process -Id $env:NIGHTLY_PID -ErrorAction SilentlyContinue; "
            "if ($p) { @{start=$p.StartTime.ToFileTimeUtc().ToString(); executable=$p.Path} | ConvertTo-Json -Compress } else { 'null' }",
            NIGHTLY_PID=str(pid),
        )
    )


def restart(package, check_only=False, deadline=None):
    from scripts.codex_package.idle_tasks import busy_threads

    cli = package / "bin/codex.exe"
    info = json.loads(
        subprocess.check_output(
            [str(cli), "app-server", "daemon", "version"], text=True
        )
    )
    if Path(info["managedCodexPath"]).resolve() != cli.resolve():
        return {"status": "deferred", "reason": "Selected package changed"}
    if info["status"] != "running":
        return {"status": "not-running"}
    if info.get("backend") != "pid":
        return {"status": "deferred", "reason": "Running server is unmanaged"}
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    pid_file = home / "app-server-daemon/daemon.pid"
    record = pid_file.read_text()
    identity = json.loads(record)
    pid = identity["pid"]
    process = process_identity(pid)
    if not process or process["start"] != identity["processStartTime"]:
        raise RuntimeError("Stale daemon PID record")
    expected = json.loads((package / "codex-package.json").read_text())["version"]
    if (
        info["appServerVersion"] == expected
        and Path(process["executable"]).resolve() == cli.resolve()
    ):
        return {"status": "already-current", "version": expected}
    socket_path = home / "app-server-control/app-server-control.sock"
    with connect_socket(socket_path, "ws://localhost/rpc") as connection:
        request_id = 0

        async def rpc(method, params):
            nonlocal request_id
            request_id += 1
            connection.send(
                json.dumps({"id": request_id, "method": method, "params": params})
            )
            while True:
                response = json.loads(connection.recv(timeout=60))
                if response.get("id") == request_id:
                    if "error" in response:
                        raise RuntimeError(response["error"])
                    return response["result"]

        asyncio.run(
            rpc(
                "initialize",
                {
                    "clientInfo": {"name": "codex-nightly", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            )
        )
        connection.send(json.dumps({"method": "initialized"}))
        busy = asyncio.run(busy_threads(rpc))
    if busy:
        return {"status": "deferred", "reason": "Tasks are busy", "tasks": busy}
    if check_only:
        return {"status": "idle", "restartRequired": True}
    if (
        pid_file.read_text() != record
        or process_identity(pid) != process
        or Path(info["managedCodexPath"]).resolve() != cli.resolve()
    ):
        return {"status": "deferred", "reason": "Daemon or selection changed"}
    # One shutdown request closes admission and drains; never send a second or force-kill.
    with connect_socket(socket_path, "ws://localhost/daemon/shutdown") as connection:
        connection.send(str(pid))
        if connection.recv(timeout=10) != str(pid):
            raise RuntimeError("Shutdown acknowledgment did not match the daemon PID")
    deadline = deadline if deadline is not None else time.monotonic() + 1800
    while process_identity(pid) == process:
        if time.monotonic() >= deadline:
            return {"status": "deferred", "reason": "Daemon is still draining"}
        time.sleep(1)
    if Path(info["managedCodexPath"]).resolve() != cli.resolve():
        return {"status": "deferred", "reason": "Selected package changed"}
    subprocess.run([str(cli), "app-server", "daemon", "start"], check=True)
    after = json.loads(
        subprocess.check_output(
            [str(cli), "app-server", "daemon", "version"], text=True
        )
    )
    new = json.loads(pid_file.read_text())
    if (
        after["appServerVersion"] != expected
        or Path(process_identity(new["pid"])["executable"]).resolve() != cli.resolve()
    ):
        raise RuntimeError("Restart did not load the verified package")
    return {"status": "restarted", "version": expected}
