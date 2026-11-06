#!/usr/bin/env python3
"""Create and reap only process groups launched by this runner's private registry."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import traceback


def birth(pid):
    """Identify a still-live leader across PID reuse, without inspecting argv."""
    statfile = Path('/proc') / str(pid) / 'stat'
    if statfile.exists():
        return statfile.read_text().rsplit(')', 1)[1].split()[19]
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='],
                            capture_output=True, text=True, timeout=3)
    value = result.stdout.strip()
    if not value:
        raise ProcessLookupError(pid)
    return value


def live_group(pgid):
    result = subprocess.run(['ps', '-axo', 'pgid=,stat='], capture_output=True,
                            text=True, timeout=3, check=True)
    for row in result.stdout.splitlines():
        parts = row.split()
        if len(parts) == 2 and parts[0] == str(pgid) and not parts[1].startswith('Z'):
            return True
    return False


def cleanup(directory, token, selected):
    for path in Path(directory).glob('*.json'):
        if selected and path.name != selected + '.json':
            continue
        record = json.loads(path.read_text())
        pgid = record.get('pgid')
        if record.get('token') != token or not isinstance(pgid, int) or pgid <= 1 or pgid == os.getpgrp():
            raise ValueError('invalid owned review group')
        # The private registry is made for this invocation and never reused on
        # restart. A surviving leader must still be the session/group leader.
        try:
            # Darwin may deny getsid() across sessions. The launcher already
            # created the session; group identity plus birth protects PID reuse.
            if os.getpgid(pgid) != pgid:
                raise ValueError('review process identity changed')
            if birth(pgid) != record.get('birth'):
                raise ValueError('review process PID was reused')
        except ProcessLookupError:
            pass  # Its orphan children remain in the explicitly owned group.
        try:
            os.killpg(pgid, signal.SIGTERM)
            time.sleep(.05)
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # On Darwin a group consisting only of terminated/zombie processes
            # can reject KILL with EPERM after TERM. Confirm there is no live
            # member instead of converting an already-finished review to error.
            if live_group(pgid):
                raise
        path.unlink(missing_ok=True)


def main():
    operation, directory, token = sys.argv[1:4]
    if operation == 'launch':
        os.setsid()
        pid = os.getpid()
        owner = int(os.environ.get('CK_PROCESS_OWNER_PID', os.getppid()))
        if owner <= 1:
            raise ValueError('managed process requires a live runner owner')
        owner_birth = birth(owner)
        path = Path(directory) / (str(pid) + '.json')
        fd, temporary = tempfile.mkstemp(prefix='.group-', dir=directory)
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump({'pgid': pid, 'token': token, 'birth': birth(pid),
                           'owner': owner, 'owner_birth': owner_birth}, out)
                out.flush()
                os.fsync(out.fileno())
            # Publish only complete records; cleanup may run during launch.
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        command = sys.argv[4:]
        child = subprocess.Popen(command)
        next_check = 0
        while child.poll() is None:
            if time.monotonic() >= next_check:
                try:
                    same_owner = birth(owner) == owner_birth
                except (OSError, subprocess.SubprocessError):
                    same_owner = False
                if not same_owner:
                    # EXIT traps cannot run after SIGKILL. The supervisor stays
                    # in the owned group and kills itself and every member of its process group.
                    os.killpg(pid, signal.SIGKILL)
                next_check = time.monotonic() + 1
            time.sleep(.05)
        rc = child.wait()
        raise SystemExit(rc if rc >= 0 else 128 - rc)
    elif operation == 'cleanup':
        cleanup(directory, token, sys.argv[4] if len(sys.argv) > 4 else '')
    else:
        raise ValueError('unknown operation')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        location = traceback.extract_tb(error.__traceback__)[-1].lineno
        print('review process group ' + sys.argv[1] + f' (line {location}): ' + str(error), file=sys.stderr)
        sys.exit(1)
