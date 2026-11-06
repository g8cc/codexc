#!/usr/bin/env python3
"""Local leaf snapshots and recoverable acceptance. Never invokes a model."""
import base64
import datetime
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid

STATE = Path('.codingkeeper')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True).encode()


def sync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data, mode=0o600):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.leaf-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path):
    return json.loads(Path(path).read_text())


def queue_entries(data):
    if len(data) > 4 * 1024 * 1024 or b'\0' in data:
        raise ValueError('queue exceeds 4 MiB or contains NUL')
    section = ''
    lines = data.decode('utf-8').splitlines(keepends=True)
    consumed = -1
    ready = False
    fence = None
    entries = []
    for i, line in enumerate(lines):
        if i <= consumed:
            continue
        text = line.strip()
        if text.startswith(('```', '~~~')):
            marker = text[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is not None:
            continue
        if text.startswith('##'):
            section = text.lstrip('#').strip().lower()
            ready = ready or section == 'ready'
        elif section == 'ready' and (text.startswith('- [ ]') or text.startswith('- [x]') or text.startswith('- [X]')):
            task = text[5:].strip()
            if task:
                indent = len(line) - len(line.lstrip())
                continuation = []
                for j, following in enumerate(lines[i + 1:], i + 1):
                    stripped = following.strip()
                    depth = len(following) - len(following.lstrip())
                    if not stripped:
                        continue
                    if stripped.startswith('#') or depth <= indent:
                        break
                    continuation.append(stripped)
                    consumed = j
                if text.startswith('- [ ]'):
                    entries.append((i, '\n'.join([task, *continuation])))
            elif text.startswith('- [ ]'):
                raise ValueError('empty ready checkbox on line ' + str(i + 1))
        elif section == 'ready' and re.match(r'^-\s*\[', text):
            raise ValueError('malformed ready checkbox on line ' + str(i + 1))
    if not ready:
        raise ValueError('queue has no ## ready section')
    if fence is not None:
        raise ValueError('queue has an unclosed code fence')
    return entries


def read_queue(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
            raise ValueError('queue must be a regular file no larger than 4 MiB')
        data = source.read(4 * 1024 * 1024 + 1)
    queue_entries(data)  # Validate the entire queue before dispatching even its first leaf.
    return data


def done_queue(data, task):
    lines = data.decode('utf-8').splitlines(keepends=True)
    for i, found in queue_entries(data):
        if found == task:
            lines[i] = lines[i].replace('- [ ]', '- [x]', 1)
            return ''.join(lines).encode('utf-8')
    raise ValueError('accepted task line not found in queue.md')


def git(*args, optional=False):
    run = subprocess.run(['git', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if run.returncode and not optional:
        raise ValueError('git snapshot failed: ' + run.stderr.decode('utf-8', 'replace').strip())
    return run.stdout if not run.returncode else None


def snapshot(directory, save=False):
    # Non-Git legacy runners have no source inventory. This limitation is explicit
    # in their evidence; strict leaf entrypoints require a Git working tree.
    git_root = git('rev-parse', '--show-toplevel', optional=True)
    if git_root is None:
        return {'git': False, 'head': None, 'index_sha256': None, 'files': {}}
    root = Path(os.fsdecode(git_root).strip()).resolve()
    if root != Path.cwd().resolve():
        raise ValueError('run leaf tasks from the Git repository root')
    head = git('rev-parse', '--verify', 'HEAD', optional=True)
    index = git('ls-files', '--stage', '-z')
    names = git('ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')
    names.extend(os.fsencode(str(p)) for p in (STATE / 'gate.sh', STATE / 'review-leaf.sh') if p.exists() or p.is_symlink())
    if len(set(names)) > 50000:
        raise ValueError('snapshot exceeds the 50000-path budget')
    total = 0
    files = {}
    blobs = directory / 'blobs'
    if save:
        blobs.mkdir(exist_ok=True)
        (STATE / 'evidence' / '.blobs').mkdir(exist_ok=True)
    for raw in sorted(set(names)):
        if not raw:
            continue
        name = os.fsdecode(raw)
        if name.startswith(('.codingkeeper/', '.codexc/')) and name not in ('.codingkeeper/gate.sh', '.codingkeeper/review-leaf.sh'):
            continue
        path = Path(name)
        try:
            info = path.lstat()
        except FileNotFoundError:
            files[name] = {'kind': 'missing'}
            continue
        if stat.S_ISLNK(info.st_mode):
            data = os.fsencode(os.readlink(path))
            kind = 'symlink'
        elif stat.S_ISREG(info.st_mode):
            total += info.st_size
            if info.st_size > 16 * 1024 * 1024 or total > 128 * 1024 * 1024:
                raise ValueError('snapshot exceeds 16 MiB/file or 128 MiB/source budget: ' + name)
            fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                actual = os.fstat(stream.fileno())
                if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
                    raise ValueError('source changed during snapshot: ' + name)
                data = stream.read(16 * 1024 * 1024 + 1)
                after = os.fstat(stream.fileno())
            if len(data) != info.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                raise ValueError('source changed during snapshot: ' + name)
            kind = 'file'
        elif stat.S_ISDIR(info.st_mode):
            # Gitlinks need their checkout identity as well as the parent index.
            child = subprocess.run(['git', '-C', name, 'rev-parse', 'HEAD'], capture_output=True)
            dirty = subprocess.run(['git', '-C', name, 'status', '--porcelain'], capture_output=True)
            if child.returncode or dirty.returncode or dirty.stdout:
                raise ValueError('unverifiable or dirty submodule: ' + name)
            data = child.stdout
            kind = 'gitlink'
        else:
            raise ValueError('unsupported source file: ' + name)
        sha = digest(data)
        files[name] = {'kind': kind, 'mode': stat.S_IMODE(info.st_mode), 'sha256': sha, 'size': len(data)}
        if save and not (blobs / sha).exists():
            shared = STATE / 'evidence' / '.blobs' / sha
            if not shared.exists():
                atomic(shared, data)
            os.link(shared, blobs / sha)
    if head != git('rev-parse', '--verify', 'HEAD', optional=True) or index != git('ls-files', '--stage', '-z'):
        raise ValueError('Git HEAD/index changed during snapshot')
    return {'git': True, 'head': os.fsdecode(head).strip() if head else None, 'index_sha256': digest(index), 'files': files}


def manifest(directory, which):
    return read_json(directory / (which + '.json'))


def fingerprint(value):
    return digest(encode(value))


def begin(task_b64):
    active = STATE / 'active-leaf.json'
    if active.exists():
        old = read_json(active)
        directory = STATE / 'evidence' / old['id']
        if old['task_b64'] == task_b64 and (directory / 'baseline.json').is_file():
            print(directory.resolve())
            return
    ident = uuid.uuid4().hex
    directory = STATE / 'evidence' / ident
    directory.mkdir(parents=True, mode=0o700)
    baseline = snapshot(directory, save=True)
    if os.environ.get('CODEXC_REQUIRE_GATE') == '1' and not baseline['git']:
        raise ValueError('strict leaf acceptance requires a Git repository for source evidence')
    atomic(directory / 'baseline.json', encode(baseline))
    info = {'id': ident, 'task_b64': task_b64, 'project': str(Path.cwd().resolve())}
    atomic(directory / 'leaf.json', encode(info))
    atomic(active, encode(info))
    print(directory.resolve())


def candidate(directory):
    current = snapshot(directory, save=True)
    atomic(directory / 'candidate.json', encode(current))
    baseline = manifest(directory, 'baseline')
    changed = [name for name in sorted(set(baseline['files']) | set(current['files']))
               if baseline['files'].get(name) != current['files'].get(name)]
    lines = ['Baseline HEAD: ' + str(baseline['head']), 'Candidate HEAD: ' + str(current['head']),
             'Baseline fingerprint: ' + fingerprint(baseline), 'Candidate fingerprint: ' + fingerprint(current),
             'Changed paths: ' + json.dumps(changed, ensure_ascii=True), '']
    rendered = 0
    for name in changed:
        old = baseline['files'].get(name, {})
        new = current['files'].get(name, {})
        if old.get('size', 0) + new.get('size', 0) > 256 * 1024 or rendered > 1024 * 1024:
            lines.append('Diff omitted for bounded rendering: ' + name + '; inspect manifest hashes and blobs.\n')
            continue
        before = (directory / 'blobs' / old['sha256']).read_bytes() if old.get('sha256') else b''
        after = (directory / 'blobs' / new['sha256']).read_bytes() if new.get('sha256') else b''
        if before.count(b'\n') + after.count(b'\n') > 4000:
            lines.append('Diff omitted for bounded rendering: ' + name + '; inspect manifest hashes and blobs.\n')
            continue
        try:
            a, b = before.decode('utf-8'), after.decode('utf-8')
            if '\x00' in a or '\x00' in b:
                raise UnicodeError()
            difference = list(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                                                  fromfile='baseline/' + name, tofile='candidate/' + name))
            rendered += sum(map(len, difference))
            lines.extend(difference)
        except UnicodeError:
            lines.append('Binary or symlink change: ' + name + '\n')
    atomic(directory / 'changes.diff', '\n'.join(lines).encode('utf-8'))


def receipt_present(journal, line):
    try:
        with journal.open('rb') as source:
            return any(item == line.encode('utf-8') for item in source)
    except FileNotFoundError:
        return False


def recover_locked():
    pending = STATE / 'acceptance.pending.json'
    if not pending.exists():
        return
    tx = read_json(pending)
    queue = STATE / 'queue.md'
    journal = STATE / 'journal'
    before = base64.b64decode(tx['before'])
    after = base64.b64decode(tx['after'])
    current = read_queue(queue)
    if current not in (before, after):
        raise ValueError('pending acceptance conflicts with queue edits; inspect acceptance.pending.json')
    # Commit queue, then journal. Pending is durable before either write. If the
    # second write fails, restore the task; after a crash this same protocol replays.
    try:
        if current != after:
            atomic(queue, after, tx['mode'])
        if not receipt_present(journal, tx['line']):
            fd = os.open(str(journal), os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                data = tx['line'].encode('utf-8')
                size = os.fstat(fd).st_size
                if size and os.pread(fd, 1, size - 1) != b'\n':
                    data = b'\n' + data
                offset = 0
                while offset < len(data):
                    written = os.write(fd, data[offset:])
                    if written <= 0:
                        raise OSError('journal append made no progress')
                    offset += written
                os.fsync(fd)
            finally:
                os.close(fd)
        atomic(Path(tx['directory']) / 'accepted.json', encode(tx))
    except (OSError, ValueError):
        # A confirmed journal receipt is replayable. Do not undo it and produce
        # an accepted receipt with an unchecked queue. Otherwise restore ready.
        try:
            recorded = receipt_present(journal, tx['line'])
        except OSError:
            recorded = False
        if not recorded and read_queue(queue) == after:
            atomic(queue, before, tx['mode'])
        raise
    pending.unlink()
    active = STATE / 'active-leaf.json'
    if active.exists() and read_json(active).get('id') == tx['id']:
        active.unlink()
    sync_dir(STATE)


def locked(action):
    STATE.mkdir(exist_ok=True)
    fd = os.open(str(STATE / 'acceptance.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        action()


def accept(directory, task_b64, detail):
    if (STATE / 'loop.halt').exists():
        raise ValueError('manual halt prevents new acceptance')
    if snapshot(directory) != manifest(directory, 'candidate'):
        raise ValueError('candidate changed after gate/review; refusing acceptance')
    info = read_json(directory / 'leaf.json')
    queue = STATE / 'queue.md'
    before = read_queue(queue)
    task = base64.b64decode(task_b64).decode('utf-8') if task_b64 else '(idle 持续改进)'
    after = done_queue(before, task) if task_b64 else before
    line = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' | ' + ' / '.join(task.splitlines()) + ' | ' + detail
    line += ' | receipt=' + info['id'] + ' | evidence=' + str(directory) + '\n'
    tx = {'id': info['id'], 'directory': str(directory.resolve()), 'before': base64.b64encode(before).decode(),
          'after': base64.b64encode(after).decode(), 'mode': stat.S_IMODE(queue.stat().st_mode), 'line': line,
          'baseline': fingerprint(manifest(directory, 'baseline')), 'candidate': fingerprint(manifest(directory, 'candidate'))}
    def commit():
        recover_locked()
        if (STATE / 'loop.halt').exists():
            raise ValueError('manual halt prevents new acceptance')
        # No unresolved old transaction may be overwritten.
        if read_queue(queue) != before:
            raise ValueError('queue changed during acceptance; retry from current queue')
        atomic(STATE / 'acceptance.pending.json', encode(tx))
        recover_locked()
    locked(commit)


def main():
    command = sys.argv[1]
    if command == 'next':
        data = read_queue(Path(sys.argv[2]))
        for i, task in queue_entries(data):
            print(str(i + 1) + '\t' + base64.b64encode(task.encode()).decode())
            break
    elif command == 'mark':
        path = Path(sys.argv[2]); data = read_queue(path)
        try:
            after = done_queue(data, base64.b64decode(sys.argv[3]).decode('utf-8'))
        except ValueError:
            print('not-found'); return
        atomic(path, after, stat.S_IMODE(path.stat().st_mode)); print('marked')
    elif command == 'begin':
        begin(sys.argv[2])
    elif command == 'recover':
        locked(recover_locked)
    else:
        directory = Path(sys.argv[2])
        if command == 'candidate':
            candidate(directory)
        elif command == 'verify':
            if snapshot(directory) != manifest(directory, 'candidate'):
                raise ValueError('source changed during gate/review')
        elif command == 'changed':
            print('1' if snapshot(directory)['files'] != manifest(directory, 'baseline')['files'] else '0')
        elif command == 'accept':
            accept(directory, sys.argv[3], sys.argv[4])
        else:
            raise ValueError('unknown leaf command')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, UnicodeError) as error:
        print('leaf evidence: ' + str(error), file=sys.stderr)
        sys.exit(2)
