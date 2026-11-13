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
import shutil
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
    fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32 * 1024 * 1024:
            raise ValueError('leaf metadata must be a regular file no larger than 32 MiB')
        data = source.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise ValueError('leaf metadata exceeds 32 MiB')
    return json.loads(data)


def queue_items(data):
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
        match = re.match(r'^(`{3,}|~{3,})', text)
        if match:
            marker = match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not text[len(marker):].strip():
                fence = None
            continue
        if fence is not None:
            continue
        heading = re.match(r'^##\s+(.+?)\s*#*\s*$', line)
        if heading:
            section = heading[1].strip().lower()
            ready = ready or section == 'ready'
        elif text.startswith('- [ ]') or text.startswith('- [x]') or text.startswith('- [X]'):
            task = text[5:].strip()
            if task:
                indent = len(line) - len(line.lstrip())
                continuation = []
                for j in range(i + 1, len(lines)):
                    following = lines[j]
                    stripped = following.strip()
                    depth = len(following) - len(following.lstrip())
                    if not stripped:
                        continuation.append('')
                        continue
                    if depth <= indent:
                        break
                    continuation.append(following.rstrip('\r\n'))
                    consumed = j
                # Remove only the queue's common indentation. Code indentation
                # and internal blank lines are part of the task contract.
                while continuation and not continuation[-1]:
                    continuation.pop()
                margin = min([indent + 2] + [len(item) - len(item.lstrip())
                                             for item in continuation if item.strip()])
                body = '\n'.join(item[margin:] if item else '' for item in continuation)
                contract = task + ('\n' + body if continuation else '')
                entries.append((i, contract, text.startswith('- [ ]'), section))
            elif section == 'ready' and text.startswith('- [ ]'):
                raise ValueError('empty ready checkbox on line ' + str(i + 1))
        elif section == 'ready' and re.match(r'^-\s*\[', text):
            raise ValueError('malformed ready checkbox on line ' + str(i + 1))
    if not ready:
        raise ValueError('queue has no ## ready section')
    if fence is not None:
        raise ValueError('queue has an unclosed code fence')
    return entries


def queue_entries(data):
    return [(i, task) for i, task, pending, section in queue_items(data) if pending and section == 'ready']


def queue_stats(data):
    items = queue_items(data)
    return {'ready': sum(pending and section == 'ready' for _, _, pending, section in items),
            'done': sum(not pending for _, _, pending, _ in items)}


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
        save_blob = True
        if stat.S_ISLNK(info.st_mode):
            data = os.fsencode(os.readlink(path))
            kind = 'symlink'
        elif stat.S_ISREG(info.st_mode):
            # 16 MiB/file 与 128 MiB/source 预算只约束证据 blob 存储: 超限文件
            # 流式哈希照记 (完整性不变), 内容不拷贝 — vendored 大数据文件
            # (tessdata 类) 不应剥夺炉子的验收资格 (2026-11-12 实证: 19.2 MiB
            # 的 chi_sim.traineddata.gz 让该炉永远过不了严格验收)。
            if info.st_size > 16 * 1024 * 1024 or total + info.st_size > 128 * 1024 * 1024:
                save_blob = False
            else:
                total += info.st_size
            fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                actual = os.fstat(stream.fileno())
                if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
                    raise ValueError('source changed during snapshot: ' + name)
                if save_blob:
                    data = stream.read(16 * 1024 * 1024 + 1)
                else:
                    hasher = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                        hasher.update(chunk)
                    data = None
                after = os.fstat(stream.fileno())
            if (len(data) if data is not None else info.st_size) != info.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                raise ValueError('source changed during snapshot: ' + name)
            kind = 'file'
        elif stat.S_ISDIR(info.st_mode):
            # Gitlinks need their checkout identity as well as the parent index.
            checkout = subprocess.run(['git', '-C', name, 'rev-parse', '--show-toplevel'], capture_output=True)
            if checkout.returncode or Path(os.fsdecode(checkout.stdout).strip()).resolve() != path.resolve():
                raise ValueError('uninitialized or unverifiable submodule: ' + name)
            child = subprocess.run(['git', '-C', name, 'rev-parse', 'HEAD'], capture_output=True)
            dirty = subprocess.run(['git', '-C', name, 'status', '--porcelain',
                                    '--untracked-files=all', '--ignore-submodules=none'], capture_output=True)
            if child.returncode or dirty.returncode or dirty.stdout:
                raise ValueError('unverifiable or dirty submodule: ' + name)
            data = child.stdout
            kind = 'gitlink'
        else:
            raise ValueError('unsupported source file: ' + name)
        if kind == 'file' and data is None:
            # 超限大文件: 流式哈希结果, 内容不进证据 (blob: False)
            files[name] = {'kind': kind, 'mode': stat.S_IMODE(info.st_mode),
                           'sha256': hasher.hexdigest(), 'size': info.st_size, 'blob': False}
            continue
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


def source_files(value):
    # Blob availability is storage metadata; it must not change source identity.
    return {name: {key: item for key, item in entry.items() if key != 'blob'}
            for name, entry in value['files'].items()}


def source_identity(value):
    return {**value, 'files': source_files(value)}


def fingerprint(value):
    return digest(encode(source_identity(value)))


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
    before_files, after_files = source_files(baseline), source_files(current)
    changed = [name for name in sorted(set(before_files) | set(after_files))
               if before_files.get(name) != after_files.get(name)]
    lines = ['Baseline HEAD: ' + str(baseline['head']), 'Candidate HEAD: ' + str(current['head']),
             'Baseline fingerprint: ' + fingerprint(baseline), 'Candidate fingerprint: ' + fingerprint(current),
             'Changed paths: ' + json.dumps(changed, ensure_ascii=True), '']
    rendered = 0
    for name in changed:
        old = baseline['files'].get(name, {})
        new = current['files'].get(name, {})
        if (not old.get('blob', True) or not new.get('blob', True)
                or old.get('size', 0) + new.get('size', 0) > 256 * 1024 or rendered > 1024 * 1024):
            lines.append('Diff omitted for bounded rendering: ' + name + '; inspect manifest hashes and available blobs or source files.\n')
            continue
        before = (directory / 'blobs' / old['sha256']).read_bytes() if old.get('sha256') else b''
        after = (directory / 'blobs' / new['sha256']).read_bytes() if new.get('sha256') else b''
        if before.count(b'\n') + after.count(b'\n') > 4000:
            lines.append('Diff omitted for bounded rendering: ' + name + '; inspect manifest hashes and available blobs or source files.\n')
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


def prune_evidence_locked():
    raw = os.environ.get('CODEXC_EVIDENCE_KEEP', '50')
    if not re.fullmatch(r'[0-9]{1,5}', raw) or int(raw) > 10000:
        raise ValueError('retention CODEXC_EVIDENCE_KEEP must be 0..10000')
    keep = int(raw)
    if keep == 0:
        return
    protected = set()
    for name in ('active-leaf.json', 'acceptance.pending.json'):
        path = STATE / name
        if path.exists() or path.is_symlink():
            info = read_json(path)
            ident = info.get('id') if isinstance(info, dict) else None
            if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{32}', ident):
                raise ValueError('retention cannot verify ' + name)
            protected.add(ident)
    evidence = STATE / 'evidence'
    if evidence.is_symlink():
        raise ValueError('retention evidence directory must not be a symlink')
    if not evidence.exists():
        return
    accepted = []
    for directory in evidence.iterdir():
        if (not re.fullmatch(r'[0-9a-f]{32}', directory.name)
                or directory.is_symlink() or not directory.is_dir()):
            continue
        receipt = directory / 'accepted.json'
        if not receipt.exists() or receipt.is_symlink() or not receipt.is_file():
            continue  # unaccepted work remains available for recovery/review
        info = read_json(receipt)
        if not isinstance(info, dict) or info.get('id') != directory.name:
            raise ValueError('retention cannot verify receipt: ' + str(receipt))
        accepted.append((receipt.stat().st_mtime_ns, directory.name, directory))
    # Validate all metadata before deleting anything. Protected old transactions
    # are additional to the most recent keep receipts.
    accepted.sort(reverse=True)
    protected.update(item[1] for item in accepted[:keep])
    for _, ident, directory in accepted:
        if ident not in protected:
            shutil.rmtree(directory)
    shared = evidence / '.blobs'
    if shared.is_symlink():
        raise ValueError('retention shared blob directory must not be a symlink')
    if shared.is_dir():
        for path in shared.iterdir():
            if not re.fullmatch(r'[0-9a-f]{64}', path.name):
                continue
            info = path.lstat()
            # Each retained manifest owns hard links; GC only unreferenced
            # regular blobs while snapshot writers hold this same lock.
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                path.unlink()
        sync_dir(shared)
    sync_dir(evidence)


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
    try:
        prune_evidence_locked()
    except (OSError, ValueError) as error:
        # Acceptance is already durable. A storage cleanup failure cannot revoke
        # its queue/journal receipt or make a successful task run twice.
        print('leaf evidence retention deferred: ' + str(error), file=sys.stderr)


def locked(action):
    STATE.mkdir(exist_ok=True)
    fd = os.open(str(STATE / 'acceptance.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        action()


def accept(directory, task_b64, detail):
    if (STATE / 'loop.halt').exists():
        raise ValueError('manual halt prevents new acceptance')
    if source_identity(snapshot(directory)) != source_identity(manifest(directory, 'candidate')):
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
        if source_identity(snapshot(directory)) != source_identity(manifest(directory, 'candidate')):
            raise ValueError('candidate changed while waiting for acceptance lock')
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
    elif command == 'count':
        print(queue_stats(read_queue(Path(sys.argv[2])))['ready'])
    elif command == 'mark':
        path = Path(sys.argv[2]); data = read_queue(path)
        try:
            after = done_queue(data, base64.b64decode(sys.argv[3]).decode('utf-8'))
        except ValueError:
            print('not-found'); return
        atomic(path, after, stat.S_IMODE(path.stat().st_mode)); print('marked')
    elif command == 'halt':
        STATE.mkdir(exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.halt-', dir=STATE)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(sys.argv[2])
                stream.flush(); os.fsync(stream.fileno())
            try:
                os.link(temporary, STATE / 'loop.halt')
                sync_dir(STATE)
            except FileExistsError:
                pass  # an existing operator/runner pause is authoritative
        finally:
            os.unlink(temporary)
    elif command == 'begin':
        locked(lambda: begin(sys.argv[2]))
    elif command == 'recover':
        locked(recover_locked)
    elif command == 'prune':
        locked(prune_evidence_locked)
    else:
        directory = Path(sys.argv[2])
        if command == 'candidate':
            locked(lambda: candidate(directory))
        elif command == 'verify':
            if source_identity(snapshot(directory)) != source_identity(manifest(directory, 'candidate')):
                raise ValueError('source changed during gate/review')
        elif command == 'changed':
            print('1' if source_files(snapshot(directory)) != source_files(manifest(directory, 'baseline')) else '0')
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
