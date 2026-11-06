#!/usr/bin/env python3
"""Launch one detached watcher per pane without inherited command-substitution pipes."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

def write_atomic(path, text):
    fd, name = tempfile.mkstemp(prefix='.watcher-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def launch(script, pane, owner, logfile):
    if not pane.startswith('%') or not pane[1:].isdigit() or not owner.isdigit() or int(owner) <= 1:
        raise ValueError('invalid watcher pane or owner')
    directory = Path('.codingkeeper')
    directory.mkdir(mode=0o700, exist_ok=True)
    state = directory / ('watcher-' + pane[1:] + '.json')
    fd = os.open(str(state) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('watcher launch is busy')
                time.sleep(.05)
        try:
            old = json.loads(state.read_text())
            pid = old.get('pid') if isinstance(old, dict) else None
            if isinstance(pid, int) and pid > 1 and old.get('owner') == owner:
                command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True, timeout=3)
                expected = script + ' __watcher_run ' + pane + ' ' + owner
                if command.returncode == 0 and command.stdout.strip().endswith(expected):
                    return pid
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            pass
        # Never signal a PID read from project files. An obsolete watcher exits
        # when its owner/pane dies; metadata cannot be used to kill other tasks.
        with open(logfile, 'ab', buffering=0) as log:
            child = subprocess.Popen([script, '__watcher_run', pane, owner], stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
        try:
            write_atomic(state, json.dumps({'pid':child.pid, 'owner':owner}))
            write_atomic(directory/'watcher.pid', str(child.pid)+'\n')
        except OSError:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            raise
        return child.pid
    finally:
        os.close(fd)

if __name__ == '__main__':
    try:
        print(launch(*sys.argv[1:]))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'codexc: cannot launch watcher: {error}', file=sys.stderr)
        sys.exit(1)
