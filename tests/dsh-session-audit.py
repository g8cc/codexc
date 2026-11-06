#!/usr/bin/env python3
"""Offline dsh adapter contract, matching dsh-headless's --json protocol."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SID = 'session-9d4c499c-c2ef-498e-bd42-069b1281b193'
OTHER = 'session-5d3d87e0-1a6b-4054-b602-8025a47320cc'


class DshSessionAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-dsh-session-')
        self.world = Path(self.tmp.name)
        self.session = self.world / 'session'
        self.out = self.world / 'out'
        self.call = self.world / 'call'
        self.binary = self.world / 'fake dsh'
        self.binary.write_text('#!/usr/bin/env python3\nimport json,os,sys,time\n'
                               'from pathlib import Path\n'
                               'Path(os.environ["CALL"]).write_text(json.dumps(dict(args=sys.argv[1:], task=sys.stdin.read())))\n'
                               'print(Path(os.environ["OUT"]).read_text(), flush=True)\n'
                               'time.sleep(float(os.environ.get("PAUSE", "0")))\n'
                               'sys.stderr.write(os.environ.get("ERR", ""))\n'
                               'sys.exit(int(os.environ.get("RC", "0")))\n')
        self.binary.chmod(0o755)
        self.env = dict(os.environ, DSH_BIN=str(self.binary), DSH_SESSION_FILE=str(self.session),
                        DSH_DIR=str(self.world / 'data'), OUT=str(self.out), CALL=str(self.call))

    def tearDown(self):
        self.tmp.cleanup()

    def events(self, sid=SID, text='TASK_RESULT: DONE'):
        return [dict(type='session', sessionId=sid, cwd=str(self.world)),
                dict(type='status', phase='turn_end', reason=dict(kind='completed')),
                dict(type='final', text=text)]

    def turn(self, records=None, rc=0, err=''):
        self.out.write_text('\n'.join(json.dumps(r) for r in (records if records is not None else self.events())))
        return subprocess.run([str(ROOT / 'codexc-dsh-worker')], input='task\n  code\n',
                              cwd=self.world, env=dict(self.env, RC=str(rc), ERR=err),
                              text=True, capture_output=True, timeout=5)

    def test_final_answer_and_session_are_saved_and_resumed(self):
        result = self.turn()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'TASK_RESULT: DONE')
        self.assertEqual(self.session.read_text(), SID + '\n')
        self.assertEqual(self.session.stat().st_mode & 0o777, 0o600)
        self.turn()
        call = json.loads(self.call.read_text())
        self.assertEqual(call['args'], ['--profile', 'headless', '--json', '--session-id', SID, '-'])
        self.assertEqual(call['task'], 'task\n  code\n')

    def test_failed_first_turn_retains_its_own_session_for_retry(self):
        result = self.turn(self.events(text=''), 1, 'ECONNRESET')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CK_ERROR_CLASS: transient', result.stdout)
        self.turn()
        self.assertIn(SID, json.loads(self.call.read_text())['args'])

    def test_failed_turn_cannot_replace_existing_session(self):
        self.session.write_text(SID + '\n')
        result = self.turn(self.events(OTHER), 1, 'AUTH: Authentication Fails')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CK_ERROR_CLASS: auth', result.stdout)
        self.assertEqual(self.session.read_text(), SID + '\n')

    def test_changed_session_and_wrong_cwd_fail_closed(self):
        self.session.write_text(SID + '\n')
        for events in (self.events(OTHER), [dict(type='session', sessionId=SID, cwd='/other')] + self.events()[1:]):
            with self.subTest(events=events):
                self.assertNotEqual(self.turn(events).returncode, 0)
                self.assertEqual(self.session.read_text(), SID + '\n')

    def test_only_final_answer_is_accepted(self):
        for records in (self.events(text=''), self.events()[:-1],
                        self.events() + [dict(type='final', text='')],
                        [dict(type='tool_result', text='TASK_RESULT: DONE')],
                        [dict(type='session', sessionId=SID, cwd=str(self.world)),
                         dict(type='status', phase='turn_end', reason=dict(kind='error')),
                         dict(type='final', text='TASK_RESULT: DONE')]):
            with self.subTest(records=records):
                self.assertNotEqual(self.turn(records).returncode, 0)

    def test_error_events_and_invalid_event_shapes_are_rejected(self):
        for event in (None, ['invalid'], dict(type='error', message='quota exceeded'),
                      dict(type='session', sessionId=['invalid'], cwd=str(self.world))):
            with self.subTest(event=event):
                self.assertNotEqual(self.turn(self.events() + [event]).returncode, 0)

    def test_tool_text_cannot_override_blocked_final(self):
        result = self.turn(self.events(text='TASK_RESULT: BLOCKED') + [dict(type='tool_result', text='TASK_RESULT: DONE')])
        self.assertEqual(result.stdout, 'TASK_RESULT: BLOCKED')
        self.assertEqual(result.returncode, 0)

    def test_session_is_opaque_and_whitespace_preserved(self):
        sid = 'session-opaque with spaces'
        self.session.write_text(sid + '\n')
        result = self.turn(self.events(sid))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(sid, json.loads(self.call.read_text())['args'])

    def test_corrupt_and_nonregular_session_files_stop_before_cli(self):
        for raw in ('first\nsecond\n', 'x' * 8193, '\n'):
            self.session.write_text(raw)
            self.call.unlink(missing_ok=True)
            self.assertNotEqual(self.turn().returncode, 0)
            self.assertFalse(self.call.exists())
        self.session.unlink()
        os.mkfifo(self.session)
        self.assertNotEqual(self.turn().returncode, 0)
        self.assertFalse(self.call.exists())

    def test_large_final_is_not_passed_in_argv(self):
        text = 'x' * (2 * 1024 * 1024) + '\nTASK_RESULT: DONE'
        result = self.turn(self.events(text=text))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, text)

    def test_unrelated_newest_directory_is_never_adopted(self):
        munged = '-' + (str(self.world.resolve()).rstrip('/') + '/').replace('/', '-') + '-'
        unrelated = self.world / 'data/sessions' / munged / OTHER
        unrelated.mkdir(parents=True)
        (unrelated / 'session.v4.jsonl.zstd').write_bytes(b'unrelated')
        result = self.turn()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.session.read_text(), SID + '\n')
        self.turn()
        self.assertNotIn(OTHER, json.loads(self.call.read_text())['args'])

    def test_profile_exit_codes_and_error_classes(self):
        self.env['DSH_PROFILE'] = 'custom profile'
        for rc, error, cls in ((7, 'AUTH: Authentication Fails', 'auth'),
                               (75, '429 quota exceeded', 'quota'),
                               (3, 'network timeout', 'transient'),
                               (2, 'unexpected failure', 'unknown')):
            with self.subTest(error=error):
                result = self.turn(self.events(text=''), rc, error)
                self.assertEqual(result.returncode, rc)
                self.assertIn('CK_ERROR_CLASS: ' + cls, result.stdout)
                self.assertEqual(json.loads(self.call.read_text())['args'][1], 'custom profile')

    def test_inherited_output_descriptors_do_not_hold_adapter_open(self):
        self.binary.write_text('#!/usr/bin/env python3\nimport os,sys,json,time\n'
                               'from pathlib import Path\n'
                               'sys.stdin.read()\n'
                               'if os.fork() == 0:\n    time.sleep(3)\n    os._exit(0)\n'
                               'print(Path(os.environ["OUT"]).read_text(), flush=True)\n')
        start = time.monotonic()
        result = self.turn()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - start, 2.5)

    def test_timeout_saves_identity_before_final_answer(self):
        self.out.write_text(json.dumps(self.events()[0]))
        process = subprocess.Popen([str(ROOT / 'codexc-dsh-worker')], cwd=self.world,
                                   env=dict(self.env, PAUSE='30'), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        process.stdin.write(b'task')
        process.stdin.close()
        process.stdin = None
        try:
            deadline = time.monotonic() + 3
            while not self.session.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(self.session.exists(), 'session event was not saved before timeout')
            self.assertEqual(self.session.read_text(), SID + '\n')
        finally:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
