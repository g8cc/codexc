#!/usr/bin/env python3
"""Optional offline ck status benchmark. Never included in tests/run-all.

Example:
  python3 tests/benchmark-status.py --baseline /path/to/old/codexc-headless \
      --candidate ./codexc-headless --projects 100 --repeat 3 --output /tmp/status.json

Only cmd_status and its _status_row helper are loaded. Their hardcoded registry
path is redirected to a temporary fixture. No HOME override, tmux server, worker,
model API, or real registry access is involved. Shell/helper startup within the
status reader is included; unrelated CLI argument/config setup is excluded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import tempfile
import time


def status_code(path):
    text = path.read_text(encoding='utf-8')
    start = text.index('cmd_status() {')
    end = text.index('\ncase "${1:-}" in', start)
    code = text[start:end]
    registry = '"$HOME/.codingkeeper/projects"'
    if registry not in code:
        raise ValueError(f'{path}: cannot locate registry argument safely')
    code = code.replace(registry, '"$CK_BENCH_REGISTRY"')
    return '#!/bin/bash\nset -u\n' + code + '\ncmd_status\n'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, default=Path(__file__).resolve().parents[1] / 'codexc-headless')
    parser.add_argument('--projects', type=int, default=100)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.projects <= 1000 or not 1 <= args.repeat <= 20:
        parser.error('projects must be 1..1000 and repeat 1..20')
    paths = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    result = {
        'scope': 'cmd_status aggregation including Bash and reader subprocess startup',
        'platform': platform.platform(), 'python': platform.python_version(),
        'projects': args.projects, 'repeat': args.repeat, 'warmup_each': 1,
        'fixture': 'Each project: 5 ready tasks, 3 completed tasks, journal, status.json; 20% have a live fixture PID.',
        'sources': {name: {'path': str(path), 'sha256': digest(path)} for name, path in paths.items()},
        'samples_seconds': {'baseline': [], 'candidate': []},
    }
    with tempfile.TemporaryDirectory(prefix='ck-status-bench-') as directory:
        world = Path(directory)
        registry = world / 'projects'
        projects = []
        for number in range(args.projects):
            project = world / f'bench-{number:04d}'
            state = project / '.codingkeeper'
            state.mkdir(parents=True)
            queue = '# fixture\n## ready\n' + ''.join(f'- [ ] task {i}\n' for i in range(5))
            queue += '## done\n' + ''.join(f'- [x] accepted {i}\n' for i in range(3)) + '## review-needed\n'
            (state / 'queue.md').write_text(queue)
            (state / 'journal').write_text('2026-11-05 00:00:00 | accepted fixture | accepted after 2 reviews\n')
            (state / 'status.json').write_text(json.dumps({'task': 'fixture activity', 'ts': int(time.time()), 'active': number % 5 == 0}))
            if number % 5 == 0:
                (state / 'loop.pid').write_text(str(os.getpid()) + '\n')
            projects.append(str(project))
        registry.write_text('\n'.join(projects) + '\n')
        fixtures = [p for p in world.rglob('*') if p.is_file()]
        hashes = {p: digest(p) for p in fixtures}
        scripts = {}
        for name, path in paths.items():
            scripts[name] = world / f'{name}.sh'
            scripts[name].write_text(status_code(path))
        env = dict(os.environ, CK_BENCH_REGISTRY=str(registry))

        def measure(name):
            began = time.perf_counter()
            run = subprocess.run(['/bin/bash', str(scripts[name])], cwd=world,
                                 env=env | {'CK_COMMON_DIR': str(paths[name].parent)},
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
            duration = time.perf_counter() - began
            if run.returncode or run.stderr:
                raise RuntimeError(f'{name} failed: rc={run.returncode}: {run.stderr[-1000:]}')
            if len(re.findall(r'\bbench-\d{4}\b', run.stdout)) != args.projects:
                raise AssertionError(f'{name} did not render every project')
            if run.stdout.count('5/3') != args.projects:
                raise AssertionError(f'{name} returned unexpected queue counts')
            return duration

        for name in paths:
            print(f'warmup {name}: {measure(name):.6f}s', flush=True)
        for number in range(args.repeat):
            order = ['baseline', 'candidate'] if number % 2 == 0 else ['candidate', 'baseline']
            for name in order:
                elapsed = measure(name)
                result['samples_seconds'][name].append(elapsed)
                print(f'run {number+1} {name}: {elapsed:.6f}s', flush=True)
        if any(digest(path) != checksum for path, checksum in hashes.items()):
            raise AssertionError('status reader modified the shared fixture')
        result['fixture_unchanged'] = True
    result['median_seconds'] = {name: statistics.median(samples) for name, samples in result['samples_seconds'].items()}
    old, new = result['median_seconds']['baseline'], result['median_seconds']['candidate']
    result['speedup_ratio'] = old / new
    result['median_latency_reduction_percent'] = 100 * (1 - new / old)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
