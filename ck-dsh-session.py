#!/usr/bin/env python3
"""Drive dsh's JSON protocol without guessing session ownership from disk."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

LIMIT = 16 * 1024 * 1024


def valid(sid):
    return (isinstance(sid, str) and bool(sid.strip()) and len(sid.encode('utf-8')) <= 8192
            and not any(ord(c) < 32 or ord(c) == 127 for c in sid))


def saved(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return ''
    with os.fdopen(fd, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('session store is not a regular file')
        raw = source.read(8194).decode('utf-8')
    sid = raw[:-1] if raw.endswith('\n') else raw
    if not valid(sid):
        raise ValueError('invalid saved session identity')
    return sid


def remember(path, sid):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as target:
            target.write(sid + '\n')
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def classify(text):
    if re.search(r'authentication|unauthorized|invalid.api.key|\b40[13]\b', text, re.I):
        return 'auth'
    if re.search(r'\b429\b|quota|rate.limit|usage.limit', text, re.I):
        return 'quota'
    if re.search(r'ECONNRESET|timeout|timed.out|network|connection|overloaded|bad.gateway|service.unavailable', text, re.I):
        return 'transient'
    return 'unknown'


def run():
    path = Path(os.environ.get('DSH_SESSION_FILE', '.codingkeeper/dsh-session-id'))
    expected = saved(path)
    command = [os.environ.get('DSH_BIN', 'dsh'), '--profile',
               os.environ.get('DSH_PROFILE', 'headless'), '--json']
    if expected:
        command += ['--session-id', expected]
    command += ['-']
    root, final, reason, protocol_error = '', None, None, ''
    diagnostics = ''

    def consume(line):
        nonlocal root, final, reason, protocol_error, diagnostics
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            protocol_error = 'invalid JSON stream'
            return
        if not isinstance(event, dict):
            protocol_error = 'invalid event'
            return
        kind = event.get('type')
        if kind == 'session':
            sid, cwd = event.get('sessionId'), event.get('cwd')
            if (not valid(sid) or not isinstance(cwd, str)
                    or os.path.realpath(cwd) != os.path.realpath(os.getcwd())
                    or (expected and sid != expected) or (root and root != sid)):
                protocol_error = 'session identity or working directory changed'
                return
            if protocol_error:
                return
            root = sid
            # The opening event belongs to this process. Save immediately so
            # timeout/failed turns resume it; dsh validates persisted adoption.
            remember(path, sid)
        elif kind == 'final':
            final = event.get('text')
        elif kind == 'status' and event.get('phase') == 'turn_end':
            reason = event.get('reason')
        elif kind == 'error':
            diagnostics = json.dumps(event)[-4096:]
            protocol_error = 'dsh reported an error event'

    # Regular files avoid inherited stdout pipes keeping the adapter alive
    # after the CLI exits. Outer runner owns process-group timeout/cleanup.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=output, stderr=errors)
        pending, offset = b'', 0
        try:
            while True:
                chunk = os.pread(output.fileno(), 65536, offset)
                offset += len(chunk)
                if offset > LIMIT or os.fstat(errors.fileno()).st_size > LIMIT:
                    raise ValueError('dsh output exceeds 16 MiB')
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    consume(line)
                if process.poll() is not None and not chunk:
                    break
                if not chunk:
                    time.sleep(.05)
            if pending:
                consume(pending)
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.wait()
            raise
        rc = process.wait()
        size = os.fstat(errors.fileno()).st_size
        diagnostics += os.pread(errors.fileno(), 4096, max(0, size - 4096)).decode('utf-8', 'replace')
    completed = isinstance(reason, dict) and reason.get('kind') == 'completed'
    if rc or protocol_error or not root or not completed or not isinstance(final, str) or not final.strip():
        detail = diagnostics + ' ' + json.dumps(reason)
        print('dsh turn failed: ' + (protocol_error or 'missing successful final result'))
        print(detail[-4096:])
        print('CK_ERROR_CLASS: ' + classify(detail))
        return (rc if rc > 0 else 128 - rc) if rc else 1
    sys.stdout.write(final)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, ValueError) as error:
        print('dsh adapter failed: ' + str(error))
        print('CK_ERROR_CLASS: unknown')
        sys.exit(1)
