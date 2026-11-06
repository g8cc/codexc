#!/usr/bin/env python3
"""Check only the recorded parent/child PIDs of one integration fixture."""
import argparse
from pathlib import Path
import subprocess
import sys
import time


def read_fixture_pids(path):
    lines = Path(path).read_text().splitlines()
    if len(lines) < 2 or any(not line.isascii() or not line.isdecimal() or len(line) > 10 or int(line) <= 1 for line in lines):
        raise ValueError('fixture must record both positive parent and child PIDs')
    pids = set(map(int, lines))
    if len(pids) != len(lines):
        raise ValueError('fixture PID records must be distinct')
    return pids


def live_processes(pids):
    result = subprocess.run(['ps', '-p', ','.join(map(str, sorted(pids))), '-o', 'pid=,stat='],
                            capture_output=True, text=True, timeout=3)
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise RuntimeError('cannot inspect fixture processes: ' + result.stderr.strip())
    live = {}
    for line in result.stdout.splitlines():
        pid, state = line.split()
        if int(pid) in pids and not state.startswith('Z'):
            # A stopped process is still alive. Only exit/zombie has terminated
            # execution; a zombie may await its reaper briefly after tree kill.
            live[int(pid)] = state
    return live


def wait_exited(path, timeout=2):
    pids = read_fixture_pids(path)
    deadline = time.monotonic() + timeout
    while True:
        live = live_processes(pids)
        if not live or time.monotonic() >= deadline:
            return live
        time.sleep(.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pidfile', type=Path)
    parser.add_argument('--timeout', type=float, default=2)
    args = parser.parse_args()
    try:
        live = wait_exited(args.pidfile, args.timeout)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('fixture exit check failed: ' + str(error), file=sys.stderr)
        return 1
    if live:
        print('fixture processes survived: ' + str(live), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
