import os
import signal
import subprocess
import sys
import time
from pathlib import Path

GIB = 1024**3
log_dir = Path(os.environ["BUILD_LOG_DIR"])
log_dir.mkdir()
peak = 0
peak_pss = 0
minimum = float("inf")
aborted = False


def sample(pgid):
    info = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    available = int(info["MemAvailable"].split()[0]) * 1024
    rows = subprocess.check_output(["ps", "-eo", "pid=,pgid=,rss="], text=True)
    members = [row.split() for row in rows.splitlines() if int(row.split()[1]) == pgid]
    rss = sum(int(row[2]) * 1024 for row in members)
    pss = 0
    for pid, _, _ in members:
        try:
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    pss += int(line.split()[1]) * 1024
        except ProcessLookupError:
            pass
        except FileNotFoundError:
            pass
    return available, rss, pss


with (
    (log_dir / "build.log").open("w") as output,
    (log_dir / "memory.csv").open("w", buffering=1) as metrics,
):
    metrics.write("elapsed_seconds,available_bytes,build_rss_bytes,build_pss_bytes\n")
    available, _, _ = sample(-1)
    if available < GIB:
        sys.exit("Refusing build: less than 1 GiB available")
    proc = subprocess.Popen(
        sys.argv[1:], stdout=output, stderr=subprocess.STDOUT, start_new_session=True
    )
    started = time.monotonic()
    last_report = -30
    try:
        while proc.poll() is None:
            elapsed = time.monotonic() - started
            available, rss, pss = sample(proc.pid)
            peak = max(peak, rss)
            peak_pss = max(peak_pss, pss)
            minimum = min(minimum, available)
            metrics.write(f"{elapsed:.1f},{available},{rss},{pss}\n")
            if elapsed - last_report >= 30:
                print(
                    f"{elapsed:.0f}s: RSS {rss / GIB:.2f} GiB, PSS {pss / GIB:.2f} GiB, available {available / GIB:.2f} GiB, peak RSS {peak / GIB:.2f} GiB",
                    flush=True,
                )
                last_report = elapsed
            if available < GIB:
                aborted = True
                print("ABORT: memory threshold crossed", flush=True)
                break
            time.sleep(1)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            time.sleep(2)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        result = proc.wait()
        summary = f"exit={result}, aborted={aborted}, peak_rss_gib={peak / GIB:.3f}, peak_pss_gib={peak_pss / GIB:.3f}, min_available_gib={minimum / GIB:.3f}\n"
        (log_dir / "summary.txt").write_text(summary)
        print(summary, flush=True)
sys.exit(125 if aborted else result)
