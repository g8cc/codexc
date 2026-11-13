#!/usr/bin/env python3
"""Log migration preserves legacy content and follows the shared log location."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LogLocationAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-logs-', dir='/private/tmp')
        self.world = Path(self.tmp.name)
        self.legacy = self.world / 'legacy codex'
        self.legacy.mkdir()
        self.home = self.world / 'home'
        self.home.mkdir()
        self.target = self.home / '.codingkeeper'
        self.env = {**os.environ, 'HOME': str(self.home), 'CODEX_HOME': str(self.legacy),
                    'CODEXC_LOOP_NOTIFY': '0', 'CODEXC_NOTIFY': '0'}
        self.env.pop('CODEXC_LOG_DIR', None)

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self):
        return subprocess.run(['python3', str(ROOT / 'ck-log.py'), str(self.target), str(self.legacy)],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_shared_logger_migrates_and_appends_without_losing_history(self):
        old = self.legacy / 'codexc-watch.log'
        old.write_text('old history\n')
        source = '. ' + shlex.quote(str(ROOT / 'ck-common.sh')) + '\nlog new-message\n'
        for _ in range(2):
            result = subprocess.run(['/bin/bash', '-c', source], env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        log = self.target / 'codexc-watch.log'
        self.assertTrue(log.exists(), 'shared logs should live under .codingkeeper')
        self.assertTrue(log.read_text().startswith('old history\n'))
        self.assertEqual(log.read_text().count('old history'), 1)
        self.assertEqual(log.read_text().count('new-message'), 2)
        self.assertFalse(old.exists())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_concurrent_migration_is_idempotent_for_both_logs(self):
        for name in ('codexc-watch.log', 'codexc-daily.log'):
            (self.legacy / name).write_text(name + ' history\n')
        processes = [subprocess.Popen(['python3', str(ROOT / 'ck-log.py'), str(self.target), str(self.legacy)],
                                     env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(5)]
        for process in processes:
            out, err = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, err)
        for name in ('codexc-watch.log', 'codexc-daily.log'):
            self.assertEqual((self.target / name).read_text(), name + ' history\n')

    def test_existing_new_and_old_logs_are_both_preserved(self):
        self.target.mkdir()
        (self.target / 'codexc-watch.log').write_text('new\n')
        (self.legacy / 'codexc-watch.log').write_text('old\n')
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.target / 'codexc-watch.log').read_text(), 'new\n')
        self.assertEqual((self.legacy / 'codexc-watch.log').read_text(), 'old\n')

    def test_first_headless_start_prepares_and_migrates_log_before_auto_init(self):
        old = self.legacy / 'codexc-watch.log'
        old.write_text('legacy startup history\n')
        source = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        body = r'''
register_project() { :; }
notify() { :; }
cmd_init() {
    printf 'scaffold output\n'
    printf '## ready\n' > .codingkeeper/queue.md
    printf 'fixture complete\n' > .codingkeeper/loop.halt
}
run_runner
'''
        env = self.env | {'CODEXC_HEADLESS_CMD': 'true', 'CODEXC_LOOP_IDLE': '0',
                          'CODEXC_REQUIRE_GATE': '0', 'CODEXC_AUTO_RESUME': '0', 'CODEXC_ACTIVE_WINDOW': ''}
        result = subprocess.run(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-headless')],
                                cwd=self.world, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.world / '.codingkeeper/queue.md').is_file())
        output = (self.target / 'codexc-watch.log').read_text()
        self.assertTrue(output.startswith('legacy startup history\n'))
        self.assertIn('scaffold output', output)
        self.assertFalse(old.exists())

    def test_failure_tail_keeps_chinese_reason_and_never_changes_source(self):
        path = self.world / 'worker output'
        data = ('旧' * 1000 + '\n真实故障：连接失败\n').encode('utf-8')
        path.write_bytes(data)
        result = subprocess.run(['python3', str(ROOT / 'ck-log.py'), '--tail', str(path), '120'],
                                cwd=self.world, env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('真实故障：连接失败', result.stdout)
        self.assertNotIn('\n', result.stdout)
        self.assertLess(len(result.stdout.encode('utf-8')), 130)
        self.assertEqual(path.read_bytes(), data)

    def test_failure_tail_rejects_fifo_and_symlink_without_blocking(self):
        regular = self.world / 'regular'
        regular.write_text('keep')
        fifo, link = self.world / 'fifo', self.world / 'link'
        os.mkfifo(fifo); link.symlink_to(regular)
        for path in (fifo, link):
            with self.subTest(path=path.name):
                result = subprocess.run(['python3', str(ROOT / 'ck-log.py'), '--tail', str(path), '120'],
                                        cwd=self.world, env=self.env, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(regular.read_text(), 'keep')

    def test_log_fifo_fails_without_waiting(self):
        self.target.mkdir()
        os.mkfifo(self.target / 'codexc-watch.log')
        self.assertNotEqual(self.prepare().returncode, 0)


if __name__ == '__main__':
    unittest.main()
