#!/usr/bin/env python3
"""Project-scoped live human sessions. No model calls or session deletion."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

ROOT = Path(__file__).resolve().parent
def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

leaf = module('interaction_leaf', 'ck-leaf.py')
process = module('interaction_process', 'ck-review-process.py')
DIRECTORY = leaf.STATE / 'interactive'
TOKEN = re.compile(r'[0-9a-f]{32}')

def records():
    if DIRECTORY.is_symlink():
        raise ValueError('interactive directory must not be a symlink')
    if not DIRECTORY.exists():
        return []
    result = []
    for path in DIRECTORY.glob('*.json'):
        if len(result) >= 128 or not TOKEN.fullmatch(path.stem):
            raise ValueError('invalid interactive session catalog')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError('interactive session must be a regular file')
            raw = source.read(2049)
        if len(raw) > 2048:
            raise ValueError('interactive session exceeds read budget')
        value = json.loads(raw)
        if (not isinstance(value, dict) or type(value.get('owner')) is not int
                or value['owner'] <= 1 or not isinstance(value.get('birth'), str)
                or not 1 <= len(value['birth']) <= 128):
            raise ValueError('invalid interactive session record')
        result.append((path, value))
    return result

def live(value):
    try:
        os.kill(value['owner'], 0)
        return process.birth(value['owner']) == value['birth']
    except ProcessLookupError:
        return False

def active():
    return any(live(value) for _, value in records())

def begin(owner):
    if owner <= 1:
        raise ValueError('interactive owner must be a live PID')
    value = {'owner': owner, 'birth': process.birth(owner)}
    os.kill(owner, 0)
    token = secrets.token_hex(16)
    def save():
        existing = records()
        for path, record in existing:
            if not live(record):
                path.unlink()
        if sum(live(record) for _, record in existing) >= 128:
            raise ValueError('too many live interactive sessions')
        DIRECTORY.mkdir(exist_ok=True)
        leaf.atomic(DIRECTORY / (token + '.json'), leaf.encode(value))
    leaf.locked(save)
    return token

def end(token=None, owner=None):
    if owner is not None and owner <= 1:
        raise ValueError('invalid interactive owner')
    if token is not None and not TOKEN.fullmatch(token):
        raise ValueError('invalid interactive session token')
    def remove():
        for path, value in records():
            if (token and path.stem == token) or (owner and value['owner'] == owner):
                path.unlink()
        if DIRECTORY.exists():
            leaf.sync_dir(DIRECTORY)
    leaf.locked(remove)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('begin'); start.add_argument('--owner', type=int, required=True)
    finish = sub.add_parser('end'); finish.add_argument('token')
    release = sub.add_parser('release-owner'); release.add_argument('owner', type=int)
    sub.add_parser('check')
    args = parser.parse_args()
    try:
        if args.command == 'begin':
            print(begin(args.owner))
        elif args.command == 'end':
            end(token=args.token)
        elif args.command == 'release-owner':
            end(owner=args.owner)
        else:
            blocked = active()
            print('interactive' if blocked else 'ready')
            return 125 if blocked else 0
    except (OSError, ValueError, process.subprocess.SubprocessError) as error:
        parser.exit(2, 'interaction: ' + str(error) + '\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
