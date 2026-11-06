#!/usr/bin/env python3
import importlib.util
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

spec = importlib.util.spec_from_file_location('leaves', Path(__file__).resolve().parents[1]/'ck-leaves.py')
leaves = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leaves)


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root/'.codingkeeper'
        self.state.mkdir()
        (self.state/'gate.sh').write_text('#!/bin/bash\nset -e\nnode --test\n')

    def codes(self, source):
        (self.state/'queue.md').write_bytes(source.encode() if isinstance(source, str) else source)
        return {f['code'] for f in leaves.audit(self.root)['findings']}

    def test_hidden_pending(self):
        self.assertIn('unreachable-task', self.codes('## ready\n## done\n- [ ] STAB-BE-01 pending\n'))

    def test_duplicate_id_and_section(self):
        self.assertEqual({'duplicate-id', 'duplicate-section'}, self.codes('## ready\n- [ ] ENG-02 task\n## ready\n- [ ] ENG-02 changed\n'))

    def test_bad_utf8_fails(self):
        self.assertEqual({'queue-unreadable'}, self.codes(b'## ready\n\xff'))

    def test_fenced_examples_ignored(self):
        self.assertEqual(set(), self.codes('## ready\n```md\n## done\n- [ ] ENG-01 example\n```\n'))

    def test_unclosed_fence_rejected(self):
        self.assertIn('unclosed-code-fence', self.codes('## ready\n```md\n- [ ] ENG-01 example\n'))

    def test_fence_with_info_is_not_a_closing_fence(self):
        self.codes('## ready\n```md\n```example\n- [ ] ENG-01 example\n```\n')
        result = leaves.audit(self.root)
        self.assertEqual(result['ready'], 0)
        self.assertEqual(result['findings'], [])

    def test_multiline_with_spaces_and_blocked(self):
        self.assertEqual(set(), self.codes('## ready\n- [ ]   FP-IOS-01 task\n  - 验收: actual request succeeds\n## blocked\n- [ ] FP-IOS-02 task\n'))

    def test_nested_acceptance_checkboxes_are_not_ready_tasks(self):
        self.codes('## ready\n- [ ] ENG-01 implement\n  - [ ] ENG-01 acceptance step\n    ## done\n- [ ] ENG-02 next\n')
        result = leaves.audit(self.root)
        self.assertEqual(result['ready'], 2)
        self.assertEqual(result['findings'], [])

    def test_placeholder_gate(self):
        (self.state/'gate.sh').write_text('echo "gate placeholder"\nexit 0\n')
        self.assertIn('placeholder-gate', self.codes('## ready\n- [ ] FP-IOS-01 task\n'))

    def test_done_history_is_not_new_task(self):
        self.assertEqual(set(), self.codes('## ready\n## done\n- [x] ENG-02 history\n'))

    def test_invalid_checkbox(self):
        self.assertIn('malformed-checkbox', self.codes('## ready\n- [] lost\n'))

    def test_special_queue_and_gate_files_fail_without_blocking(self):
        for name, code in (('queue.md', 'queue-unreadable'), ('gate.sh', 'gate-unreadable')):
            with self.subTest(name=name):
                (self.state / 'queue.md').write_text('## ready\n- [ ] ENG-01 task\n')
                target = self.state / name
                target.unlink()
                os.mkfifo(target)
                try:
                    result = subprocess.run([sys.executable, str(Path(leaves.__file__)),
                                             str(self.root), '--json'],
                                            capture_output=True, text=True, timeout=2)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(code, result.stdout)
                finally:
                    target.unlink()


if __name__ == '__main__':
    unittest.main()
