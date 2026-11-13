#!/usr/bin/env python3
"""Read-only cross-project overnight results and human decisions."""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time

spec = importlib.util.spec_from_file_location('leaf', Path(__file__).with_name('ck-leaf.py'))
leaf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leaf)
pack_spec = importlib.util.spec_from_file_location('fuel_packs', Path(__file__).with_name('ck-fuel-packs.py'))
packs = importlib.util.module_from_spec(pack_spec)
pack_spec.loader.exec_module(packs)


def read(path, limit=1024 * 1024, tail=False):
    fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(str(path) + ' must be a regular file')
        if not tail and info.st_size > limit:
            raise ValueError(str(path) + ' exceeds read budget')
        cut = tail and info.st_size > limit
        if cut:
            stream.seek(info.st_size - limit)
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError(str(path) + ' exceeds read budget')
        if cut:
            data = data.split(b'\n', 1)[-1]
    return data.decode('utf-8')


def status_fresh(status, now):
    timestamp = status.get('ts')
    return type(timestamp) in (int, float) and -5 <= now - timestamp <= 120


def project_report(project, since):
    state = project / '.codingkeeper'
    result = {'project': str(project), 'accepted': [], 'decisions': [],
              'ready': 0, 'halt': '', 'status': {}, 'status_fresh': False, 'configured_packs': [], 'errors': []}
    for name in ('queue.md', 'journal', 'loop.halt', 'status.json', 'fuel-packs.json'):
        path = state / name
        try:
            if name == 'queue.md':
                items = leaf.queue_items(leaf.read_queue(path))
                result['ready'] = sum(pending and section == 'ready' for _, _, pending, section in items)
                result['decisions'] = [task for _, task, pending, section in items
                                       if pending and section == 'review-needed']
            elif name == 'journal':
                for line in read(path, tail=True).splitlines():
                    if ' | receipt=' not in line or ' | (park) | ' in line:
                        continue
                    try:
                        timestamp = dt.datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S').timestamp()
                    except ValueError:
                        continue
                    if since <= timestamp <= time.time() + 60:
                        result['accepted'].append(line)
            elif name == 'fuel-packs.json':
                result['configured_packs'] = packs.validate_profile(json.loads(read(path, limit=60 * 1024)))
            elif name == 'loop.halt':
                result['halt'] = read(path, limit=65536).strip() or 'paused by operator'
            else:
                value = json.loads(read(path))
                if not isinstance(value, dict):
                    raise ValueError('status.json must contain an object')
                result['status'] = value
                result['status_fresh'] = status_fresh(value, time.time())
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError) as error:
            result['errors'].append(str(error))
    result['accepted_count'] = len(result['accepted'])
    result['decision_count'] = len(result['decisions'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--hours', type=int, default=12)
    parser.add_argument('--project', type=Path, help='only report one project')
    args = parser.parse_args()
    if not 1 <= args.hours <= 168:
        parser.error('--hours must be 1..168')
    paths = []
    errors = []
    if args.project:
        paths.append(args.project.resolve())
    else:
        try:
            registry = read(Path.home() / '.codingkeeper/projects')
            paths.extend(Path(line.strip()).resolve() for line in registry.splitlines()
                         if line.strip() and not line.lstrip().startswith('#'))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError) as error:
            errors.append(str(error))
        if (Path.cwd() / '.codingkeeper').is_dir():
            paths.append(Path.cwd().resolve())
    now = int(time.time())
    report = {'generated_at': now, 'hours': args.hours,
              'projects': [project_report(path, now - args.hours * 3600)
                           for path in dict.fromkeys(paths)], 'errors': errors}
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f'CodingKeeper 晨报 · 最近 {args.hours} 小时')
        for item in report['projects']:
            print(f"\n{item['project']} · 已验收 {item['accepted_count']} · 待决策 {item['decision_count']} · 待执行 {item['ready']}")
            if item['configured_packs']:
                print('  配置领域: ' + '、'.join(packs.PACKS[name][0] for name in item['configured_packs']))
            status = item['status']
            if item['halt']:
                print('  阻塞/暂停: ' + item['halt'])
            elif status:
                stale = not item['status_fresh']
                print('  状态: ' + str(status.get('phase', 'unknown')) + (' (状态已陈旧)' if stale else ''))
            for line in item['accepted'][-20:]:
                print('  成果: ' + line)
            for decision in item['decisions'][:20]:
                print('  待决策: ' + decision.replace('\n', '\n    '))
            for error in item['errors']:
                print('  读取问题: ' + error)
        for error in errors:
            print('读取问题: ' + error)
    return 0


if __name__ == '__main__':
    sys.exit(main())
