#!/usr/bin/env python3
"""Live human-session arbitration in private projects, without model calls."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class InteractionAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-interaction-', dir='/private/tmp')
        self.world = Path(self.tmp.name)
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        (self.state / 'queue.md').write_text('## ready\n- [ ] first task\n- [ ] second task\n')
        self.bin = self.world / 'bin'; self.bin.mkdir()
        ps = self.bin / 'ps'
        ps.write_text('#!/bin/bash\nprintf "%s\\n" "${CK_FAKE_BIRTH:-fixture birth}"\n')
        ps.chmod(0o755)
        self.env = {**os.environ, 'HOME': str(self.world / 'home'),
                    'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'CODEXC_ACTIVE_WINDOW': '', 'CODEXC_LOOP_NOTIFY': '0', 'CODEXC_NOTIFY': '0',
                    'CODEXC_REQUIRE_GATE': '0', 'CODEXC_HEADLESS_CMD': 'touch invoked',
                    'CODEXC_AUTO_RESUME': '0', 'CODEXC_BANNER': '0'}
        self.owner = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])

    def tearDown(self):
        self.owner.terminate(); self.owner.wait(timeout=5)
        self.tmp.cleanup()

    def cli(self, *args, cwd=None):
        return subprocess.run([str(ROOT / 'ck'), 'interaction', *args],
                              cwd=cwd or self.world, env=self.env, capture_output=True, text=True, timeout=10)

    def begin(self):
        result = self.cli('begin', '--owner', str(self.owner.pid))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def shell(self, body, timeout=60):
        source = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        result = subprocess.run(['/bin/bash', '-c', source + '\n' + body, str(ROOT / 'codexc-headless')],
                                cwd=self.world, env=self.env, capture_output=True, text=True, timeout=timeout)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_live_human_blocks_only_the_current_project_and_end_preserves_queue(self):
        queue = (self.state / 'queue.md').read_bytes()
        token = self.begin()
        self.assertEqual(self.cli('check').returncode, 125)
        other = self.world / 'other'; other.mkdir()
        self.assertEqual(self.cli('check', cwd=other).returncode, 0)
        self.assertEqual(self.cli('end', token).returncode, 0)
        self.assertEqual(self.cli('end', token).returncode, 0)
        self.assertEqual(self.cli('check').returncode, 0)
        self.assertEqual((self.state / 'queue.md').read_bytes(), queue)

    def test_two_humans_cannot_release_each_other_by_token(self):
        one = self.begin(); two = self.begin()
        self.cli('end', one)
        self.assertEqual(self.cli('check').returncode, 125)
        self.assertTrue((self.state / 'interactive' / (two + '.json')).exists())
        self.cli('end', two)
        self.assertEqual(self.cli('check').returncode, 0)

    def test_dead_or_reused_owner_does_not_block_automation(self):
        self.begin()
        self.env['CK_FAKE_BIRTH'] = 'new process birth'
        self.assertEqual(self.cli('check').returncode, 0)
        self.env.pop('CK_FAKE_BIRTH')
        self.owner.terminate(); self.owner.wait(timeout=5)
        self.assertEqual(self.cli('check').returncode, 0)

    def test_invalid_or_linked_interaction_state_fails_closed(self):
        token = self.begin()
        path = self.state / 'interactive' / (token + '.json')
        original = path.read_bytes()
        path.write_text('invalid json')
        self.assertEqual(self.cli('check').returncode, 2)
        path.unlink()
        target = self.world / 'target'; target.write_bytes(original)
        path.symlink_to(target)
        self.assertEqual(self.cli('check').returncode, 2)
        self.assertEqual(target.read_bytes(), original)

    def test_ending_interaction_resumes_the_first_ready_task(self):
        token = self.begin()
        result = self.shell(r'''
register_project() { :; }
notify() { :; }
sleep() { python3 "$CK_COMMON_DIR/ck-interaction.py" end TOKEN >/dev/null; }
headless_turn() { printf '%s\n' "$1" >> calls; touch .codingkeeper/loop.halt; return 125; }
run_runner
'''.replace('TOKEN', token))
        calls = (self.world / 'calls').read_text()
        self.assertIn('first task', calls)
        self.assertNotIn('second task', calls)
        self.assertNotIn('- [x]', (self.state / 'queue.md').read_text())

    def test_new_human_session_stops_only_the_owned_worker_group(self):
        body = r'''
CODEXC_HEADLESS_CMD='touch started; sleep 20; touch escaped'
(command sleep 1; python3 "$CK_COMMON_DIR/ck-interaction.py" begin --owner OWNER >/dev/null) &
headless_turn 'first task' .codingkeeper/out
printf 'worker_rc=%s\n' "$?"
wait
'''.replace('OWNER', str(self.owner.pid))
        result = self.shell(body, timeout=15)
        self.assertIn('worker_rc=125', result.stdout)
        self.assertTrue((self.world / 'started').exists())
        self.assertFalse((self.world / 'escaped').exists())

    def test_daily_rescue_checks_the_target_project_interaction(self):
        self.begin()
        source=(ROOT/'codexc-daily').read_text().rsplit('\ncase "${1:-run}" in',1)[0]
        body=r'''
TARGET_PROJECT="$PWD"
mkdir launcher
cd launcher
notify() { :; }
sleep() { :; }
latest_rollout() { printf ignored; }
latest_cwd() { printf '%s.' "$TARGET_PROJECT"; }
last_turn_state() { printf died; }
resolve_session_name() { printf audit; }
send_text() { printf SENT; }
tmux() {
 case "$*" in
  *'#{session_path}'*|*'#{pane_current_path}'*) printf '%s' "$TARGET_PROJECT" ;;
  *'#{pane_id}'*) printf '%%1' ;;
  *'#{pane_current_command}'*|*'@codexc_tool'*) printf codex ;;
  *) return 0 ;;
 esac
}
run_now
'''
        env=self.env | {'CODEXC_DAILY_IDLE':'0'}
        result=subprocess.run(['/bin/bash','-c',source+'\n'+body,str(ROOT/'codexc-daily')],
                              cwd=self.world,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('SENT',result.stdout)

    def test_runner_waits_for_human_without_dispatch_or_cursor_progress(self):
        self.begin()
        result = self.shell(r'''
register_project() { :; }
notify() { :; }
sleep() { cp .codingkeeper/status.json waiting.json; touch .codingkeeper/loop.halt; }
run_runner
''')
        self.assertFalse((self.world / 'invoked').exists(), result.stderr)
        status = json.loads((self.world / 'waiting.json').read_text())
        self.assertEqual(status['phase'], 'waiting_interaction')
        self.assertFalse(status['active'])
        self.assertFalse((self.state / 'burn-cursor.json').exists())
        self.assertIn('- [ ] first task', (self.state / 'queue.md').read_text())

if __name__ == '__main__':
    unittest.main(verbosity=2)
