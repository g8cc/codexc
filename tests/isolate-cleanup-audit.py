#!/usr/bin/env python3
"""isolate.py scratch-world lifecycle: green runs clean up, failed runs keep triage artifacts.

61 leaked ck-tests-* worlds (~9.6 GiB) tripped the 2026-11-14 disk alarm: the
wrapper killed its process group and private tmux server but never removed its
own mkdtemp directory.
"""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IsolateCleanupAudit(unittest.TestCase):
    def run_isolate(self, *stage):
        return subprocess.run([sys.executable, str(ROOT / 'tests/isolate.py'), *stage],
                              cwd=ROOT, text=True, capture_output=True, timeout=300)

    def artifacts_path(self, result):
        match = re.search(r'Test artifacts: (\S+)', result.stdout)
        self.assertIsNotNone(match, result.stdout + result.stderr)
        return Path(match.group(1))

    def test_successful_run_removes_its_scratch_world(self):
        result = self.run_isolate('unit')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        artifacts = self.artifacts_path(result)
        self.assertFalse(artifacts.exists(),
                         'isolate must remove its scratch world after a green run')

    def test_failed_run_keeps_artifacts_for_triage(self):
        result = self.run_isolate('nosuchstage')
        self.assertNotEqual(result.returncode, 0)
        artifacts = self.artifacts_path(result)
        self.assertTrue(artifacts.exists(), 'failed runs must keep logs for triage')
        self.assertIn('test artifacts kept for triage', result.stderr)
        shutil.rmtree(artifacts, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
