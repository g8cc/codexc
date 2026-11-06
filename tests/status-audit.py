#!/usr/bin/env python3
"""Bounded status reads and large queue regressions, without model calls."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StatusAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-status-audit-')
        self.addCleanup(self.tmp.cleanup)
        self.world = Path(self.tmp.name)
        self.home = self.world / 'home'
        (self.home / '.codingkeeper').mkdir(parents=True)
        self.registry = self.home / '.codingkeeper/projects'
        self.registry.write_text(str(self.world) + '\n')
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        (self.state / 'queue.md').write_text('## ready\n- [ ] task\n')
        self.env = dict(os.environ, HOME=str(self.home))

    def status(self):
        return subprocess.run([str(ROOT / 'ck'), 'status'], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_fifo_state_files_do_not_block_other_projects(self):
        other = self.world / 'other-project'
        (other / '.codingkeeper').mkdir(parents=True)
        (other / '.codingkeeper/queue.md').write_text('## ready\n- [ ] other\n')
        with self.registry.open('a') as registry:
            registry.write(str(other) + '\n')
        for name in ('status.json', 'loop.pid', 'watcher.pid', 'journal'):
            with self.subTest(name=name):
                path = self.state / name
                os.mkfifo(path)
                try:
                    result = self.status()
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('1/0', result.stdout)
                    self.assertIn('other-project', result.stdout)
                finally:
                    path.unlink()

    def test_fifo_registry_does_not_block(self):
        self.registry.unlink()
        os.mkfifo(self.registry)
        result = self.status()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_large_journal_reads_latest_complete_record(self):
        with (self.state / 'journal').open('wb') as journal:
            journal.write(b'old history\n' * 100000)
            journal.write('2026-11-06 | latest accepted | receipt\n'.encode())
        result = self.status()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('latest accepted', result.stdout)

    def test_oversized_status_is_ignored(self):
        (self.state / 'loop.pid').write_text(str(os.getpid()))
        (self.state / 'status.json').write_text(json.dumps(
            dict(task='oversize activity' + 'x' * (1024 * 1024), active=True, ts=__import__('time').time())))
        result = self.status()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('任务执行中', result.stdout)

    def test_journal_tail_drops_partial_record_before_latest_receipt(self):
        (self.state / 'journal').write_text(
            '2026-11-06 | stale receipt | ' + 'x' * (1024 * 1024 + 100)
            + '\n2026-11-06 | newest receipt | accepted\n')
        result = self.status()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('newest receipt', result.stdout)
        self.assertNotIn('stale receipt', result.stdout)

    def test_large_queue_dispatch_finishes_within_poll_interval(self):
        queue = self.state / 'queue.md'
        queue.write_text('## ready\n' + ''.join('- [ ] task ' + str(i) + '\n' for i in range(40000)))
        result = subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), 'count', str(queue)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '40000')

    def test_benchmark_runs_without_inherited_library_path(self):
        env = self.env.copy()
        env.pop('CK_COMMON_DIR', None)
        result = subprocess.run(['python3', str(ROOT / 'tests/benchmark-status.py'),
                                 '--baseline', str(ROOT / 'codexc-headless'),
                                 '--projects', '2', '--repeat', '1'],
                                env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('fixture_unchanged', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
