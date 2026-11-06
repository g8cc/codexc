#!/usr/bin/env python3
"""Locked, atomic edits to provider configuration; preserve unknown settings."""
import contextlib
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

@contextlib.contextmanager
def config_file(path):
    path = Path(path).resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = os.open(str(path) + '.codingkeeper-lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('configuration is busy; try again')
                time.sleep(.05)
        original = path.read_text(encoding='utf-8') if path.exists() else ''
        yield path, original
    finally:
        os.close(lock)

def replace(path, text):
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            os.fchmod(out.fileno(), mode)
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def codex(path, action, projects):
    try:
        import tomllib
    except ImportError:
        raise ValueError('python3 >= 3.11 is required for safe TOML configuration updates')
    with config_file(path) as (path, original):
        data = tomllib.loads(original)
        text = original
        if action == 'retry':
            provider = data.get('model_providers', {}).get('custom')
            if not isinstance(provider, dict):
                return
            missing = {k: v for k, v in {'request_max_retries': 8, 'stream_max_retries': 10, 'stream_idle_timeout_ms': 300000}.items() if k not in provider}
            if not missing:
                return
            lines = text.splitlines(keepends=True)
            start = None
            for i, line in enumerate(lines):
                if not line.lstrip().startswith('['):
                    continue
                # Parse table headers semantically (spacing and quoted keys included).
                try:
                    header = tomllib.loads(line)
                except tomllib.TOMLDecodeError:
                    continue
                if header == {'model_providers': {'custom': {}}}:
                    # Inside a multiline string the prefix is not valid TOML.
                    try:
                        prefix = tomllib.loads(''.join(lines[:i + 1]))
                    except tomllib.TOMLDecodeError:
                        continue
                    if not isinstance(prefix.get('model_providers', {}).get('custom'), dict):
                        continue
                    if not lines[i].endswith('\n'):
                        lines[i] += '\n'
                    start = i + 1
                    break
            if start is None:
                # An inline table cannot be reopened; do not rewrite user formatting.
                return
            lines.insert(start, ''.join(f'{k} = {v}\n' for k, v in missing.items()))
            text = ''.join(lines)
            expected = copy.deepcopy(data)
            expected['model_providers']['custom'].update(missing)
            if tomllib.loads(text) != expected:
                raise ValueError('retry update would change unrelated settings')
        else:
            existing = data.get('projects', {})
            for project in dict.fromkeys(projects):
                if project in existing:
                    continue  # Preserve explicitly untrusted as well as trusted settings.
                text += '\n[projects.' + json.dumps(project, ensure_ascii=False) + ']\ntrust_level = "trusted"\n'
        try:
            tomllib.loads(text)  # A malformed candidate is never published.
        except tomllib.TOMLDecodeError:
            if action == 'trust':
                print('codexc: projects uses a sealed inline table; automatic trust skipped, original configuration preserved', file=sys.stderr)
                return
            raise
        if text != original:
            replace(path, text)

def claude(path, mode, projects):
    with config_file(path) as (path, original):
        data = json.loads(original) if original else {}
        if not isinstance(data, dict):
            raise ValueError('Claude configuration must be a JSON object')
        entries = data.setdefault('projects', {})
        if not isinstance(entries, dict):
            raise ValueError('Claude projects must be a JSON object')
        data['hasCompletedOnboarding'] = True
        if mode == '1':
            data['bypassPermissionsModeAccepted'] = True
        for project in dict.fromkeys(projects):
            entry = entries.setdefault(project, {})
            if not isinstance(entry, dict):
                raise ValueError('Claude project entry must be a JSON object')
            entry.update(hasTrustDialogAccepted=True, hasCompletedProjectOnboarding=True)
        if original and data == json.loads(original):
            return
        replace(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')

if __name__ == '__main__':
    try:
        tool, path, action, *projects = sys.argv[1:]
        if tool == 'codex':
            codex(path, action, projects)
        elif tool == 'claude':
            claude(path, action, projects)
        else:
            raise ValueError('unknown configuration type')
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f'codexc: configuration unchanged: {error}', file=sys.stderr)
        sys.exit(1)
