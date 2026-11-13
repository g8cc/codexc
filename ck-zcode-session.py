#!/usr/bin/env python3
"""ZCode wire IDs and a durable retry session, separate from useful context."""
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
ID = re.compile(r'sess_[A-Za-z0-9_-]{1,200}')
NOTICE = (r'额度已领到（[0-9]+(?:,[0-9]{3})* token），'
          r'[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} 起生效，'
          r'还有约 [0-9]+ 分钟。\s*'
          r'这是套餐的生效规则，不是报错；到点直接用即可，不用重试。')


def valid(sid):
    return isinstance(sid, str) and ID.fullmatch(sid) is not None


def saved(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return ''
    with os.fdopen(fd, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('stored ZCode sessionId is not a regular file')
        raw = source.read(257)
    if len(raw) > 256:
        raise ValueError('stored ZCode sessionId exceeds 256 bytes')
    sid = raw.decode('utf-8').strip()
    if not valid(sid):
        raise ValueError('invalid stored ZCode sessionId in ' + str(path))
    return sid


def session_db():
    override = os.environ.get('ZCODE_SESSION_DB')
    if override:
        return Path(override)
    return Path.home() / '.zcode/cli/db/db.sqlite'


def row_exists(sid):
    import sqlite3
    db = session_db()
    if not db.is_file():
        return True  # db 缺失/不可读时宁可保守, 不清链
    try:
        with sqlite3.connect(db, timeout=5) as conn:
            return conn.execute('SELECT 1 FROM session WHERE id=?', (sid,)).fetchone() is not None
    except sqlite3.Error:
        return True


def heal(path, sid):
    # resume 目标行已被清理 (废弃链清扫) 时旧链不可续: 删 sid 文件,
    # 让下一轮以全新会话起步, 不在死链上无限失败
    if not valid(sid) or row_exists(sid):
        return 0
    for stale in (path, Path(str(path) + '.retry')):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass
    print('zcode session chain gone; cleared for a fresh start')
    return 0


def write_session(path, sid):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.zcode-session-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(sid + '\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def records(raw):
    text = raw.decode('utf-8')
    try:
        return [json.loads(text)]
    except (ValueError, RecursionError):
        result = []
        for line in text.splitlines():
            try:
                result.append(json.loads(line))
            except (ValueError, RecursionError):
                continue
        return result


def read_output(path):
    with path.open('rb') as source:
        raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('response exceeds 16 MiB')
    return raw


def metadata(record):
    # Tool/subagent event IDs are not the worker conversation. The installed
    # CLI emits turn.started before requesting the model, and a final result.
    return (isinstance(record, dict) and 'sessionId' in record
            and (record.get('type') in ('turn.started', 'result')
                 or 'type' not in record))



def cli_environment(cjs, base=None):
    env = dict(os.environ if base is None else base)
    key = 'ZCODE_BUILTIN_PROVIDER_CONFIG_FILE'
    # The bootstrap reads CONFIG_FILE; BUNDLED_CONFIG_FILE is its output.
    # Keep an explicit input authoritative, with the earlier bundled override
    # accepted as a compatibility seed when the actual input is absent.
    bundled_key = 'ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE'
    if key not in env and env.get(bundled_key, '').strip():
        env[key] = env[bundled_key]
    if key not in env:
        directory = Path(cjs).resolve().parent
        # CLI development builds use glm/provider; packaged apps keep the
        # signed built-in config beside glm under Resources/config/provider.
        candidates = (directory / 'provider/zcode-builtin.json',
                      directory.parent / 'config/provider/zcode-builtin.json')
        for path in candidates:
            if path.is_file():
                env[key] = str(path)
                break
    # Do not supply a personal path: with only the bundled seed, the SDK
    # prepares its normal endpoint-specific active cache and personal default.
    # Explicit provider paths, endpoint and credentials stay inherited.
    return env


def capture(path, out, err, resumed, command):
    pending = Path(str(path) + '.retry')
    root = resumed

    def remember(record):
        nonlocal root
        if not metadata(record) or not valid(record['sessionId']):
            return
        sid = record['sessionId']
        if root and root != sid:
            return
        if not root:
            # Save before the model finishes: timeout/SIGKILL must not cause
            # the next attempt to allocate another conversation.
            write_session(pending, sid)
            root = sid

    with out.open('wb') as stdout, err.open('wb') as stderr:
        env = cli_environment(command[1]) if len(command) > 1 and Path(command[0]).name == 'node' else None
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env)
        offset, buffer = 0, b''
        with out.open('rb') as source:
            while True:
                chunk = source.read(64 * 1024)
                offset += len(chunk)
                if offset > LIMIT or err.stat().st_size > LIMIT:
                    process.kill()
                    process.wait()
                    raise ValueError('response exceeds 16 MiB')
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        remember(json.loads(line))
                    except (ValueError, RecursionError):
                        continue
                if process.poll() is not None and not chunk:
                    break
                if not chunk:
                    time.sleep(0.05)
        rc = process.wait()
    # Pretty JSON and an unterminated last event are also accepted.
    for record in records(read_output(out)):
        remember(record)
    return rc if rc >= 0 else 128 - rc


def finish(path, out, resumed):
    output = records(read_output(out))
    response, sid, root = None, None, resumed
    for record in output:
        if not isinstance(record, dict):
            continue
        if record.get('type') in (None, 'result') and 'response' in record:
            response = record['response']
    if not isinstance(response, str) or not response.strip():
        raise ValueError('missing final response')
    if re.fullmatch(NOTICE, response.strip()):
        print('zcode turn deferred: package quota is not active yet')
        print('CK_ERROR_CLASS: quota')
        return 75
    for record in output:
        if metadata(record):
            candidate = record['sessionId']
            if not valid(candidate):
                raise ValueError('invalid sessionId')
            if root and candidate != root:
                raise ValueError('ZCode changed the resumed sessionId')
            root = sid = candidate
    if sid:
        write_session(path, sid)
        Path(str(path) + '.retry').unlink(missing_ok=True)
    sys.stdout.write(response)
    return 0


def main():
    action, session, *args = sys.argv[1:]
    if action == 'exec':
        if not args:
            raise ValueError('exec requires a CLI command')
        os.execvpe(args[0], args, cli_environment(session))
    path = Path(session)
    if action == 'select':
        print(saved(path) or saved(Path(session + '.retry')), end='')
        return 0
    if action == 'capture':
        out, err, resumed, *command = args
        return capture(path, Path(out), Path(err), resumed, command)
    if action == 'heal':
        return heal(path, args[0])
    if action == 'finish':
        out, resumed = args
        return finish(path, Path(out), resumed)
    raise ValueError('unknown session operation')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RecursionError) as exc:
        print('codexc-zcode-worker: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
