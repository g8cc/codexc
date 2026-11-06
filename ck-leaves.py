#!/usr/bin/env python3
"""Offline queue audit. Never invokes a worker, a gate, or a model."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

LIMIT = 2 * 1024 * 1024
CHECK = re.compile(r'^\s*-\s+\[([ xX])\]\s+(.+?)\s*$')
IDENT = re.compile(r'^([A-Za-z]+(?:-[A-Za-z0-9]+)+|M\d+[A-Za-z0-9-]*)\b')


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('audit input must be a regular file')
        raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('audit input exceeds 2 MiB')
    return raw


def audit(project):
    project = Path(project).expanduser().resolve()
    result = dict(project=str(project), counts={}, findings=[])

    def finding(severity, code, line, detail):
        result['findings'].append(dict(severity=severity, code=code, line=line, detail=detail))

    queue = project / '.codingkeeper/queue.md'
    try:
        raw = read_regular(queue)
        source = raw.decode('utf-8')
        if '\0' in source:
            raise ValueError('queue contains NUL')
    except (OSError, ValueError) as exc:
        finding('error', 'queue-unreadable', 0, type(exc).__name__)
        return result
    section, fence = '', None
    ids, headings, tasks = {}, {}, []
    lines = source.splitlines()
    consumed = 0
    for number, line in enumerate(lines, 1):
        if number <= consumed:
            continue
        stripped = line.strip()
        match = re.match(r'^(`{3,}|~{3,})', stripped)
        if match:
            token = match[1]
            if fence is None:
                fence = token
            elif (token[0] == fence[0] and len(token) >= len(fence)
                  and not stripped[len(token):].strip()):
                fence = None
            continue
        if fence:
            continue
        heading = re.match(r'^##\s+(.+?)\s*#*\s*$', line)
        if heading:
            section = heading[1].strip().lower()
            if section in headings:
                finding('error', 'duplicate-section', number, 'duplicate section: ' + section)
            headings[section] = number
            continue
        m = CHECK.match(line)
        if not m:
            if re.match(r'^\s*-\s*\[', line):
                finding('error', 'malformed-checkbox', number, 'use - [ ] task or - [x] task')
            continue
        checked, task = m[1].lower() == 'x', m[2]
        # Nested checkboxes/headings belong to this task's acceptance contract,
        # matching the dispatch parser rather than inflating the ready count.
        indent = len(line) - len(line.lstrip())
        for following_number in range(number + 1, len(lines) + 1):
            following = lines[following_number - 1]
            if not following.strip():
                continue
            if len(following) - len(following.lstrip()) <= indent:
                break
            consumed = following_number
        count_key = section + (':checked' if checked else ':pending')
        result['counts'][count_key] = result['counts'].get(count_key, 0) + 1
        tasks.append((number, section, checked, task))
        ident = IDENT.match(task)
        if ident:
            ident = ident[1].upper()
            if ident in ids:
                finding('error', 'duplicate-id', number, f'{ident} already appears on line {ids[ident]}')
            ids[ident] = number
        if not checked and section not in ('ready', 'review-needed', 'blocked', 'backlog'):
            finding('error', 'unreachable-task', number, 'pending checkbox outside ready/review-needed/blocked/backlog')
        if checked and section == 'ready':
            finding('warning', 'completed-in-ready', number, 'move accepted history to done after reconciling evidence')
        if not checked and section == 'ready':
            if any(x in task for x in ('通读本仓库', '列出 3 个最有价值', '持续改进', '全面优化')):
                finding('warning', 'unbounded-task', number, 'specify a demonstrated gap, scope, and acceptance before execution')
            if re.search(r'(?:只需|仅需|只要).*(?:存在|字符串|文件名)', task):
                finding('warning', 'weak-evidence', number, 'existence/text assertions alone do not prove user behavior')
    if fence is not None:
        finding('error', 'unclosed-code-fence', 0, 'close the code fence before declaring more tasks')
    if 'ready' not in headings:
        finding('error', 'missing-ready', 0, 'queue must declare ## ready, even when empty')
    gate = project / '.codingkeeper/gate.sh'
    if any(section == 'ready' and not checked for _, section, checked, _ in tasks):
        try:
            body = read_regular(gate).decode('utf-8')
            if re.search(r'gate placeholder|CK_GATE_PLACEHOLDER', body, re.I):
                finding('error', 'placeholder-gate', 0, 'ready tasks have an official placeholder gate')
            if re.search(r'(?:grep|rg).*\\?\[x', body) and 'phase=' in body:
                finding('warning', 'gate-task-count', 0, 'gate strength depends on task count; decouple before queue cleanup')
        except (OSError, ValueError):
            finding('error', 'gate-unreadable', 0, 'ready tasks require a readable gate')
    result['pending'] = sum(v for k, v in result['counts'].items() if k.endswith(':pending'))
    result['ready'] = result['counts'].get('ready:pending', 0)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('projects', nargs='*', help='project roots (default: current directory)')
    parser.add_argument('--registry', action='store_true', help='audit ~/.codingkeeper/projects')
    parser.add_argument('--json', action='store_true', help='machine-readable findings; no task bodies')
    args = parser.parse_args()
    projects = args.projects
    if args.registry:
        try:
            projects += [line.strip() for line in (Path.home()/'.codingkeeper/projects').read_text(encoding='utf-8').splitlines() if line.strip() and not line.lstrip().startswith('#')]
        except (OSError, UnicodeError) as exc:
            parser.exit(2, f'registry unreadable: {type(exc).__name__}\n')
    results = [audit(p) for p in dict.fromkeys(projects or ['.'])]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"{result['project']}: ready={result.get('ready', 0)}, pending={result.get('pending', 0)}")
            for f in result['findings']:
                print(f"  {f['severity']} L{f['line']} {f['code']}: {f['detail']}")
        print('Offline structure check only; project value and acceptance evidence require source review.')
    return int(any(f['severity'] == 'error' for r in results for f in r['findings']))


if __name__ == '__main__':
    sys.exit(main())
