#!/usr/bin/env python3
"""Accepted evidence retention preserves recoverable work and shared content."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EvidenceRetentionAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-retention-', dir='/private/tmp')
        self.world = Path(self.tmp.name)
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        self.evidence = self.state / 'evidence'
        self.shared = self.evidence / '.blobs'
        self.shared.mkdir(parents=True)
        (self.state / 'queue.md').write_text('## ready\n- [ ] task\n')
        self.env = {**os.environ, 'CODEXC_EVIDENCE_KEEP': '2'}

    def tearDown(self):
        self.tmp.cleanup()

    def helper(self, *args, success=True):
        result = subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), *map(str, args)],
                                cwd=self.world, env=self.env, capture_output=True,
                                text=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def history(self, number, accepted=True):
        ident = f'{number:032x}'
        directory = self.evidence / ident
        directory.mkdir()
        (directory / 'blobs').mkdir()
        content = self.shared / f'{number:064x}'
        content.write_text('content ' + str(number))
        os.link(content, directory / 'blobs' / content.name)
        if accepted:
            receipt = directory / 'accepted.json'
            receipt.write_text(json.dumps({'id': ident}))
            os.utime(receipt, (number, number))
        return directory

    def test_prunes_old_accepted_work_and_unreferenced_shared_blobs(self):
        old = self.history(1)
        recent = [self.history(2), self.history(3)]
        unaccepted = self.history(4, accepted=False)
        shared_content = self.shared / f'{1:064x}'
        os.link(shared_content, recent[0] / 'blobs' / shared_content.name)
        journal = self.state / 'journal'
        journal.write_text('permanent acceptance history\n')
        self.helper('prune')
        self.assertFalse(old.exists())
        self.assertTrue(all(path.exists() for path in recent + [unaccepted]))
        self.assertTrue(shared_content.exists(), 'retained evidence still references this blob')
        self.assertEqual(journal.read_text(), 'permanent acceptance history\n')
        orphan = self.shared / ('f' * 64)
        orphan.write_text('unreferenced')
        self.helper('prune')
        self.assertFalse(orphan.exists())

    def test_active_and_pending_are_protected_even_if_old_and_accepted(self):
        active = self.history(1)
        pending = self.history(2)
        for i in range(3, 7):
            self.history(i)
        (self.state / 'active-leaf.json').write_text(json.dumps({'id': active.name}))
        marker = self.state / 'acceptance.pending.json'
        marker.write_text(json.dumps({'id': pending.name}))
        before = marker.read_bytes()
        self.helper('prune')
        self.assertTrue(active.exists())
        self.assertTrue(pending.exists())
        self.assertEqual(marker.read_bytes(), before)

    def test_invalid_state_prevents_any_deletion_and_zero_disables_retention(self):
        directories = [self.history(i) for i in range(1, 5)]
        marker = self.state / 'active-leaf.json'
        marker.write_text('{invalid')
        self.assertNotEqual(self.helper('prune', success=False).returncode, 0)
        self.assertTrue(all(path.exists() for path in directories))
        marker.unlink()
        self.env['CODEXC_EVIDENCE_KEEP'] = '0'
        self.helper('prune')
        self.assertTrue(all(path.exists() for path in directories))

    def test_acceptance_runs_retention_after_the_transaction_is_durable(self):
        old = self.history(1)
        self.history(2)
        directory = Path(self.helper('begin', 'dGFzaw==').stdout.strip())
        self.helper('candidate', directory)
        self.helper('accept', directory, 'dGFzaw==', 'accepted')
        self.assertFalse(old.exists())
        self.assertTrue((directory / 'accepted.json').exists())
        self.assertFalse((self.state / 'acceptance.pending.json').exists())
        self.assertIn('- [x] task', (self.state / 'queue.md').read_text())

    def test_retention_failure_does_not_undo_confirmed_acceptance(self):
        self.env['CODEXC_EVIDENCE_KEEP'] = 'invalid'
        directory = Path(self.helper('begin', 'dGFzaw==').stdout.strip())
        self.helper('candidate', directory)
        result = self.helper('accept', directory, 'dGFzaw==', 'accepted')
        self.assertIn('retention', result.stderr)
        self.assertIn('- [x] task', (self.state / 'queue.md').read_text())
        self.assertTrue((directory / 'accepted.json').exists())

    def test_control_state_fifo_fails_without_hanging(self):
        os.mkfifo(self.state / 'active-leaf.json')
        result = subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), 'begin', 'dGFzaw=='],
                                cwd=self.world, env=self.env, capture_output=True, text=True, timeout=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('regular file', result.stderr)

    def test_evidence_directory_symlinks_are_not_followed(self):
        outside = self.world / 'outside'
        outside.mkdir()
        (outside / 'keep').write_text('valuable')
        (self.evidence / ('e' * 32)).symlink_to(outside, target_is_directory=True)
        self.history(1)
        self.history(2)
        self.history(3)
        self.helper('prune')
        self.assertEqual((outside / 'keep').read_text(), 'valuable')


if __name__ == '__main__':
    unittest.main()
