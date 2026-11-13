#!/usr/bin/env python3
"""Prepare Keeper logs and read bounded UTF-8 failure tails without locale loss."""
import fcntl
import os
from pathlib import Path
import stat
import sys


def prepare(directory, legacy):
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(directory / '.logs.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name in ('codexc-watch.log', 'codexc-daily.log'):
            old, target = legacy / name, directory / name
            if old != target and not target.exists() and not target.is_symlink() and old.exists():
                if not stat.S_ISREG(old.lstat().st_mode):
                    raise ValueError('legacy log must be a regular file: ' + str(old))
                os.rename(old, target)
            # A conflict keeps both histories intact; all future writes use target.
            fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError('log must be a regular file: ' + str(target))
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)


def failure_tail(path, limit):
    if not 1 <= limit <= 65536:
        raise ValueError('tail limit must be between 1 and 65536 bytes')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('failure tail must be a regular file')
        stream.seek(max(0, info.st_size - limit))
        # A byte limit can split a UTF-8 character. Replacement keeps the
        # diagnostic readable and valid UTF-8, including already-corrupt output.
        return stream.read(limit).decode('utf-8', 'replace').replace('\r', ' ').replace('\n', ' ')


if __name__ == '__main__':
    try:
        if len(sys.argv) == 4 and sys.argv[1] == '--tail':
            print(failure_tail(Path(sys.argv[2]), int(sys.argv[3])), end='')
        elif len(sys.argv) == 3:
            prepare(Path(sys.argv[1]), Path(sys.argv[2]))
        else:
            raise ValueError('usage: ck-log.py LOG_DIR LEGACY_DIR | --tail FILE BYTES')
    except (OSError, ValueError) as error:
        sys.exit('Keeper log preparation failed: ' + str(error))
