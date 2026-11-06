#!/usr/bin/env python3
"""Offline ZCode session continuity against the installed CLI's wire format."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import signal
import time
import unittest

REPO = Path(__file__).resolve().parent.parent
SID = 'sess_9d4c499c-c2ef-498e-bd42-069b1281b193'
NEXT = 'sess_5d3d87e0-1a6b-4054-b602-8025a47320cc'


class SessionAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-zcode-session-')
        self.root = Path(self.tmp.name)
        binary = self.root / 'bin'
        binary.mkdir()
        node = binary / 'node'
        node.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                        'from pathlib import Path\n'
                        'Path(os.environ["CALL"]).write_text(json.dumps(sys.argv[1:]))\n'
                        'sys.stdout.write(Path(os.environ["OUT"]).read_text())\n'
                        'sys.stderr.write(os.environ.get("ERR", ""))\n'
                        'sys.exit(int(os.environ.get("RC", "0")))\n')
        node.chmod(0o755)
        self.cjs = self.root / 'fake.cjs'
        self.cjs.touch()
        self.session = self.root / 'session'
        self.out = self.root / 'out'
        self.call = self.root / 'call'
        self.env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                        ZCODE_CJS=str(self.cjs), ZCODE_SESSION_FILE=str(self.session),
                        OUT=str(self.out), CALL=str(self.call), TMPDIR=str(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def turn(self, records, rc=0, err=''):
        self.out.write_text('\n'.join(json.dumps(r) for r in records))
        return subprocess.run([str(REPO / 'codexc-zcode-worker')], input='offline task',
                              cwd=self.root, env=dict(self.env, RC=str(rc), ERR=err),
                              text=True, capture_output=True, timeout=10)

    def args(self):
        return json.loads(self.call.read_text())

    def test_real_session_id_is_saved_and_resumed(self):
        result = self.turn([dict(sessionId=SID, response='TASK_RESULT: DONE')])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.session.read_text(), SID + '\n')
        result = self.turn([dict(sessionId=SID, response='TASK_RESULT: DONE')])
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.args()
        self.assertEqual(args[args.index('--resume') + 1], SID)

    def test_first_failed_turn_is_resumed_without_claiming_success(self):
        result = self.turn([dict(type='turn.started', sessionId=SID),
                            dict(type='turn.failed', sessionId=SID)], 1, 'ECONNRESET')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CK_ERROR_CLASS: transient', result.stdout)
        result = self.turn([dict(type='result', sessionId=SID, response='TASK_RESULT: DONE')])
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.args()
        self.assertIn('--resume', args)
        self.assertEqual(args[args.index('--resume') + 1], SID)

    def test_first_empty_response_is_resumed(self):
        self.assertNotEqual(self.turn([dict(sessionId=SID, response='')]).returncode, 0)
        self.turn([dict(sessionId=SID, response='TASK_RESULT: DONE')])
        self.assertIn('--resume', self.args())

    def test_malformed_stored_id_stops_before_creating_a_session(self):
        for sid in ('ses_opencode', 'sess_bad/other', '--continue', 'sess_a\nsess_b',
                    SID + ' ' * 256 + 'bad'):
            with self.subTest(sid=sid):
                self.session.write_text(sid + '\n')
                self.call.unlink(missing_ok=True)
                result = self.turn([dict(sessionId=SID, response='TASK_RESULT: DONE')])
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.call.exists())

    def test_nonregular_session_stores_do_not_block_or_start_cli(self):
        for path in (self.session, Path(str(self.session) + '.retry')):
            with self.subTest(path=path):
                os.mkfifo(path)
                try:
                    result = self.turn([dict(sessionId=SID, response='TASK_RESULT: DONE')])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(self.call.exists())
                finally:
                    path.unlink()

    def test_failed_or_quota_turn_preserves_useful_session(self):
        self.session.write_text(SID + '\n')
        result = self.turn([dict(sessionId=NEXT, response='')], 1, '401 Unauthorized')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.session.read_text(), SID + '\n')

    def test_changed_session_id_is_rejected(self):
        self.session.write_text(SID + '\n')
        result = self.turn([dict(type='result', sessionId=NEXT, response='TASK_RESULT: DONE')])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.session.read_text(), SID + '\n')

    def test_streaming_child_events_do_not_replace_worker_session(self):
        result = self.turn([dict(type='turn.started', sessionId=SID),
                            dict(type='tool.updated', sessionId=NEXT),
                            dict(type='result', sessionId=SID, response='TASK_RESULT: DONE')])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.session.read_text(), SID + '\n')

    def test_child_response_cannot_override_root_result(self):
        result = self.turn([dict(type='result', sessionId=SID, response='TASK_RESULT: BLOCKED'),
                            dict(type='tool.updated', sessionId=NEXT, response='TASK_RESULT: DONE')])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'TASK_RESULT: BLOCKED')

    def test_child_response_without_final_result_is_rejected(self):
        result = self.turn([dict(type='turn.started', sessionId=SID),
                            dict(type='tool.updated', sessionId=NEXT, response='TASK_RESULT: DONE')])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.session.exists())

    def test_timeout_preserves_session_before_cli_finishes(self):
        node = self.root / 'bin/node'
        node.write_text('#!/usr/bin/env python3\nimport json,time\n'
                        'print(json.dumps(dict(type="turn.started", sessionId=' + repr(SID) + ')), flush=True)\n'
                        'time.sleep(30)\n')
        process = subprocess.Popen([str(REPO / 'codexc-zcode-worker')], cwd=self.root,
                                   env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        process.stdin.write(b'offline task')
        process.stdin.close()
        process.stdin = None
        retry = Path(str(self.session) + '.retry')
        try:
            deadline = time.monotonic() + 5
            while not retry.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(retry.exists(), 'retry ID must be durable before the model returns')
            self.assertEqual(retry.read_text(), SID + '\n')
            self.assertFalse(self.session.exists(), 'pending context is not a useful answer')
        finally:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
        selected = subprocess.run(['python3', str(REPO / 'ck-zcode-session.py'),
                                   'select', str(self.session)], text=True, capture_output=True)
        self.assertEqual(selected.stdout, SID)

    def test_many_failures_allocate_one_session(self):
        for _ in range(3):
            self.turn([dict(type='turn.started', sessionId=SID)], 1, 'ECONNRESET')
        args = self.args()
        self.assertEqual(args[args.index('--resume') + 1], SID)
        self.assertFalse(self.session.exists())
        result = self.turn([dict(type='result', sessionId=SID, response='TASK_RESULT: DONE')])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path(str(self.session) + '.retry').exists())

    def test_invalid_final_metadata_and_failed_done_never_accept(self):
        for sid in (None, [], 'ses_foreign', 'sess_' + 'a'*201):
            with self.subTest(sid=sid):
                result = self.turn([dict(type='result', sessionId=sid, response='TASK_RESULT: DONE')])
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.session.exists())
        result = self.turn([dict(type='result', sessionId=SID, response='TASK_RESULT: DONE')], 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('TASK_RESULT: DONE\n', result.stdout)
        self.assertFalse(self.session.exists())

    def test_first_quota_notice_reuses_pending_session(self):
        notice = ('额度已领到（123 token），11-05 23:00 起生效，还有约 100 分钟。\n'
                  '这是套餐的生效规则，不是报错；到点直接用即可，不用重试。')
        result = self.turn([dict(type='result', sessionId=SID, response=notice)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CK_ERROR_CLASS: quota', result.stdout)
        self.assertFalse(self.session.exists())
        self.turn([dict(type='result', sessionId=SID, response='TASK_RESULT: DONE')])
        self.assertEqual(self.args()[self.args().index('--resume')+1], SID)


if __name__ == '__main__':
    unittest.main(verbosity=2)
