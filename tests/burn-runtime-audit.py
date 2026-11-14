#!/usr/bin/env python3
"""Burn runtime regressions using local processes, never model requests."""
import base64
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parents[1]))


class BurnRuntimeAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-burn-runtime-', dir='/private/tmp')
        self.world = Path(self.tmp.name)
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        (self.state / 'queue.md').write_text('## ready\n- [ ] task\n')
        self.env = dict(os.environ, HOME=str(self.world / 'home'),
                        CODEX_HOME=str(self.world / 'home/.codex'), CODEXC_LOOP_NOTIFY='0',
                        CODEXC_NOTIFY='0', CODEXC_LOOP_IDLE='0', CODEXC_AUTO_RESUME='0',
                        CODEXC_ACTIVE_WINDOW='', CODEXC_BANNER='0', CODEXC_HEADLESS_CMD='true',
                        CODEXC_REVIEW_PARALLEL='0', CODEXC_REQUIRE_GATE='0')
        (self.world / 'home').mkdir()
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
        for path in self.state.glob('orphan*.pid'):
            try:
                os.kill(int(path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.tmp.cleanup()

    def source(self):
        text = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        return '\n'.join('. ' + shlex.quote(str(ROOT / 'ck-common.sh'))
                         if line.startswith('. "$(dirname') else line for line in text.splitlines()) + '\n'

    def shell(self, body, timeout=60):
        process = subprocess.Popen(['/bin/bash', '-c', self.source() + body],
                                   cwd=self.world, env=self.env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.processes.append(process)
        out, err = process.communicate(timeout=timeout)
        self.assertEqual(process.returncode, 0, out + err)
        return out

    def assert_stopped(self, name='orphan.pid'):
        pid = int((self.state / name).read_text())
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
        self.assertTrue(not result.stdout.strip() or result.stdout.strip().startswith('Z'), result.stdout)

    def test_successful_worker_reaps_detached_descendants_before_gate(self):
        out = self.shell(r'''
CODEXC_HEADLESS_CMD='sleep 45 >/dev/null 2>&1 & echo $! > .codingkeeper/orphan.pid; printf "TASK_RESULT: DONE\n"'
headless_turn task .codingkeeper/out
printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=0')
        self.assert_stopped()

    def test_successful_gate_reaps_detached_descendants(self):
        (self.state / 'gate.sh').write_text('#!/bin/bash\nsleep 45 >/dev/null 2>&1 &\necho $! > .codingkeeper/orphan.pid\n')
        out = self.shell('gate_run .codingkeeper/out; printf "rc=%s" "$?"\n')
        self.assertEqual(out, 'rc=0')
        self.assert_stopped()

    def test_worker_timeout_reaps_group_and_retains_failure(self):
        out = self.shell(r'''
CODEXC_HEADLESS_TIMEOUT=1
CODEXC_HEADLESS_CMD='sleep 45 >/dev/null 2>&1 & echo $! > .codingkeeper/orphan.pid; sleep 45'
headless_turn task .codingkeeper/out; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=124')
        self.assert_stopped()

    def test_worker_manual_halt_reaps_group(self):
        out = self.shell(r'''
CODEXC_HEADLESS_CMD='sleep 45 >/dev/null 2>&1 & echo $! > .codingkeeper/orphan.pid; sleep 45'
(sleep 1; touch .codingkeeper/loop.halt) &
headless_turn task .codingkeeper/out; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=125')
        self.assert_stopped()

    def test_killed_runner_cannot_leave_worker_running(self):
        body = r'''
CODEXC_HEADLESS_CMD='sleep 45 >/dev/null 2>&1 & echo $! > .codingkeeper/orphan.pid; sleep 45'
headless_turn task .codingkeeper/out
'''
        process = subprocess.Popen(['/bin/bash', '-c', self.source() + body],
                                   cwd=self.world, env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.processes.append(process)
        deadline = time.monotonic() + 8
        while not (self.state / 'orphan.pid').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertTrue((self.state / 'orphan.pid').exists())
        # Kill only the runner, leaving its process group and worker untouched.
        process.kill(); process.wait(timeout=5)
        time.sleep(2)
        self.assert_stopped()

    def test_automatic_entry_refuses_missing_gate_before_any_worker(self):
        env = self.env.copy(); env.pop('CODEXC_REQUIRE_GATE')
        env['CODEXC_HEADLESS_CMD'] = 'touch worker-called; touch .codingkeeper/loop.halt; printf "TASK_RESULT: DONE\\n"'
        result = subprocess.run([str(ROOT / 'codexc-headless'), 'run'], cwd=self.world,
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.world / 'worker-called').exists())
        self.assertTrue((self.state / 'loop.halt').exists())

    def test_accepted_queue_task_resets_previous_idle_exhaustion(self):
        (self.state / 'queue.md').write_text('## ready\n')
        self.env['CODEXC_LOOP_IDLE'] = '1'
        self.env['CODEXC_PROMPT_ROTATION'] = '0'
        out = self.shell(r'''
register_project() { :; }
notify() { :; }
idle_turns=0
headless_turn() {
    if [ "$task_kind" = idle ]; then
        idle_turns=$((idle_turns+1))
        if [ "$idle_turns" = 1 ]; then printf '## ready\n- [ ] queued work\n' > .codingkeeper/queue.md; fi
    fi
    printf 'TASK_RESULT: DONE\n' > "$2"
}
gate_run() { : > "$1"; return 0; }
review_run() { : > "$2"; printf 0; }
run_runner
printf 'idle_turns=%s' "$idle_turns"
''')
        self.assertEqual(out, 'idle_turns=3')
        self.assertIn('- [x] queued work', (self.state / 'queue.md').read_text())

    def test_no_evidence_change_preserves_user_work_and_worker_commit(self):
        (self.state / 'queue.md').write_text('## ready\n')
        (self.world / '.gitignore').write_text('.codingkeeper/\nhome/\n')
        (self.world / 'user.txt').write_text('base\n')
        (self.world / 'worker.txt').write_text('base\n')
        for command in (['git', 'init', '-q'], ['git', 'add', '.'],
                        ['git', '-c', 'user.name=Audit', '-c', 'user.email=a@example.invalid', 'commit', '-qm', 'base']):
            subprocess.run(command, cwd=self.world, env=self.env, check=True, capture_output=True)
        (self.world / 'user.txt').write_text('user staged\n')
        subprocess.run(['git', 'add', 'user.txt'], cwd=self.world, check=True, capture_output=True)
        (self.world / 'user.txt').write_text('user staged\nuser unstaged\n')
        (self.world / 'user-new.txt').write_text('user untracked\n')
        out = self.shell(r'''
CODEXC_LOOP_IDLE=1
IDLE_PROMPT=improve
CODEXC_PROMPT_ROTATION=0
register_project() { :; }
notify() { :; }
turns=0
headless_turn() {
    turns=$((turns+1))
    if [ "$turns" = 1 ]; then
        printf 'worker change\n' > worker.txt
        printf 'worker appended\n' >> user.txt
        printf 'worker new\n' > worker-new.txt
        git -c user.name=Audit -c user.email=a@example.invalid commit -qm worker --only worker.txt || return 1
    else
        # Bound the old unsafe implementation without accepting later turns.
        touch .codingkeeper/loop.halt
    fi
    printf 'TASK_RESULT: DONE\n' > "$2"
}
gate_run() { touch gate-called; : > "$1"; }
review_run() { touch review-called; : > "$2"; printf 0; }
run_runner
printf 'turns=%s' "$turns"
''')
        self.assertEqual((self.world / 'user.txt').read_text(),
                         'user staged\nuser unstaged\nworker appended\n')
        staged = subprocess.run(['git', 'show', ':user.txt'], cwd=self.world,
                                check=True, capture_output=True, text=True).stdout
        self.assertEqual(staged, 'user staged\n')
        self.assertEqual((self.world / 'worker.txt').read_text(), 'worker change\n')
        head = subprocess.run(['git', 'log', '-1', '--format=%s'], cwd=self.world,
                              check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, 'worker')
        self.assertEqual((self.world / 'user-new.txt').read_text(), 'user untracked\n')
        self.assertEqual((self.world / 'worker-new.txt').read_text(), 'worker new\n')
        self.assertEqual(out, 'turns=1')
        self.assertIn('idle change missing evidence', (self.state / 'loop.halt').read_text())
        self.assertFalse((self.world / 'gate-called').exists())
        self.assertFalse((self.world / 'review-called').exists())
        self.assertFalse(list((self.state / 'evidence').glob('*/accepted.json')))
        self.assertFalse((self.state / 'journal').exists())

    def test_unborn_no_evidence_change_parks_without_acceptance(self):
        subprocess.run(['git', 'init', '-q'], cwd=self.world, check=True, capture_output=True)
        (self.world / 'user.txt').write_text('user unfinished\n')
        (self.state / 'queue.md').write_text('## ready\n')
        out = self.shell(r'''
IDLE_PROMPT=improve
CODEXC_PROMPT_ROTATION=0
register_project() { :; }
notify() { :; }
turns=0
headless_turn() {
    turns=$((turns+1))
    if [ "$turns" = 1 ]; then printf 'worker new\n' > worker.txt; else touch .codingkeeper/loop.halt; fi
    printf 'TASK_RESULT: DONE\n' > "$2"
}
run_runner
printf 'turns=%s' "$turns"
''')
        self.assertEqual(out, 'turns=1')
        self.assertEqual((self.world / 'user.txt').read_text(), 'user unfinished\n')
        self.assertEqual((self.world / 'worker.txt').read_text(), 'worker new\n')
        self.assertIn('idle change missing evidence', (self.state / 'loop.halt').read_text())
        self.assertFalse(list((self.state / 'evidence').glob('*/accepted.json')))

    def test_stale_review_verdict_before_final_text_cannot_accept(self):
        out = self.shell("printf 'BUGS: 0\\nFurther inspection found broken acceptance.\\n' > .codingkeeper/review; parse_bugs .codingkeeper/review\n")
        self.assertEqual(out, 'parse-fail')

    def test_unparseable_review_retries_in_loop_then_accepts(self):
        (self.state / 'queue.md').write_text('## ready\n- [ ] bounded task\n')
        self.env['CODEXC_LOOP_IDLE'] = '1'     # bounded burn noops end the loop after acceptance
        self.env['CODEXC_PROMPT_ROTATION'] = '0'
        out = self.shell(r'''
register_project() { :; }
notify() { :; }
headless_turn() { printf 'TASK_RESULT: DONE\n' > "$2"; }
gate_run() { : > "$1"; return 0; }
review_run() {
    # review_collect backgrounds this in a subshell — count via file, not var;
    # stdout mirrors the real review_run: parse_bugs verdict, not raw content
    n=$(( $(cat .codingkeeper/review.calls 2>/dev/null || echo 0) + 1 ))
    printf '%s' "$n" > .codingkeeper/review.calls
    : > "$2"
    if [ "$n" = 1 ]; then printf 'prose without verdict\n' > "$2"; printf 'parse-fail'; else printf 'no findings\nBUGS: 0\n' > "$2"; printf '0'; fi
}
run_runner
printf 'review_calls=%s' "$(cat .codingkeeper/review.calls 2>/dev/null || echo 0)"
''')
        self.assertEqual(out, 'review_calls=3')
        self.assertIn('- [x] bounded task', (self.state / 'queue.md').read_text())
        halt = (self.state / 'loop.halt').read_text() if (self.state / 'loop.halt').exists() else ''
        self.assertNotIn('review output unparseable', halt)

    def test_always_unparseable_review_parks_after_bounded_retries(self):
        (self.state / 'queue.md').write_text('## ready\n- [ ] garbage task\n')
        out = self.shell(r'''
register_project() { :; }
notify() { :; }
headless_turn() { printf 'TASK_RESULT: DONE\n' > "$2"; }
gate_run() { : > "$1"; return 0; }
review_run() {
    n=$(( $(cat .codingkeeper/review.calls 2>/dev/null || echo 0) + 1 ))
    printf '%s' "$n" > .codingkeeper/review.calls
    : > "$2"
    printf 'prose without verdict\n' > "$2"; printf 'parse-fail'
}
run_runner
printf 'review_calls=%s' "$(cat .codingkeeper/review.calls 2>/dev/null || echo 0)"
''')
        self.assertEqual(out, 'review_calls=2')
        self.assertIn('review output unparseable', (self.state / 'loop.halt').read_text())
        self.assertIn('- [ ] garbage task', (self.state / 'queue.md').read_text())

    def test_unparseable_review_breaks_consecutive_zero_streak(self):
        (self.state / 'queue.md').write_text('## ready\n- [ ] consecutive task\n')
        self.env.update(CODEXC_LOOP_IDLE='1', CODEXC_PROMPT_ROTATION='0')
        out = self.shell(r'''
register_project() { :; }
notify() { :; }
headless_turn() { printf 'TASK_RESULT: DONE\n' > "$2"; }
gate_run() { : > "$1"; return 0; }
review_run() {
    n=$(( $(cat .codingkeeper/review.calls 2>/dev/null || echo 0) + 1 ))
    printf '%s' "$n" > .codingkeeper/review.calls
    if [ "$n" = 2 ]; then
        printf 'no verdict\n' > "$2"; printf 'parse-fail'
    else
        printf 'BUGS: 0\n' > "$2"; printf '0'
    fi
}
run_runner
printf 'review_calls=%s' "$(cat .codingkeeper/review.calls)"
''')
        self.assertEqual(out, 'review_calls=4')
        self.assertIn('- [x] consecutive task', (self.state / 'queue.md').read_text())

    def test_default_reviewer_uses_cli_final_message_instead_of_transcript(self):
        bindir = self.world / 'bin'; bindir.mkdir()
        fake = bindir / 'codex'
        fake.write_text('#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\nsys.stdin.read()\n'
                        'if "--output-last-message" in sys.argv:\n'
                        '    Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(os.environ["FINAL_REVIEW"])\n'
                        'print("BUGS: 0\\nCLI transcript trailer")\n')
        fake.chmod(0o755)
        self.env.pop('CODEXC_REVIEW_CMD', None)
        self.env['PATH'] = str(bindir) + os.pathsep + self.env['PATH']
        for final, expected in (('Actual findings\nBUGS: 2\n', '2'), ('', 'parse-fail')):
            with self.subTest(final=final):
                self.env['FINAL_REVIEW'] = final
                out = self.shell('review_run task .codingkeeper/review\n')
                self.assertEqual(out, expected)

    def test_headless_selftest_failure_must_fail_the_gate(self):
        out = self.shell("parse_bugs() { printf invalid; }; cmd_selftest > selftest.log; printf 'rc=%s' \"$?\"\n")
        self.assertNotEqual(out, 'rc=0')
        self.assertIn('FAIL:', (self.world / 'selftest.log').read_text())

    def test_queue_fence_length_and_nested_headings_do_not_dispatch_examples(self):
        (self.state / 'queue.md').write_text('## ready\n````md\n```\n- [ ] example\n```\n````\n- [ ] real\n  ### acceptance\n  run tests\n')
        out = self.shell('queue_next .codingkeeper/queue.md\n')
        task = base64.b64decode(out.split('\t')[1]).decode()
        self.assertEqual(task, 'real\n### acceptance\nrun tests')

    def test_status_ready_uses_dispatch_parser(self):
        (self.state / 'queue.md').write_text('## ready\n```md\n- [ ] example\n```\n- [ ] real\n## review-needed\n- [ ] proposal\n')
        self.shell('status_write task zcode 1 100\n')
        self.assertEqual(json.loads((self.state / 'status.json').read_text())['ready'], 1)

    def test_acceptance_rechecks_candidate_after_waiting_for_transaction_lock(self):
        for command in (['git', 'init', '-q'], ['git', 'add', '.'],
                        ['git', '-c', 'user.name=Audit', '-c', 'user.email=a@example.invalid', 'commit', '-qm', 'base']):
            if command[1] == 'add':
                (self.world / '.gitignore').write_text('.codingkeeper/\nhome/\n')
                (self.world / 'product').write_text('before\n')
            subprocess.run(command, cwd=self.world, env=self.env, check=True, capture_output=True)
        self.shell('leaf_begin dGFzaw==; leaf_candidate\n')
        directory = self.state / 'evidence' / json.loads((self.state / 'active-leaf.json').read_text())['id']
        # Hold the real lock until the accept process has completed its first snapshot.
        with (self.state / 'acceptance.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            process = subprocess.Popen(['python3', str(ROOT / 'ck-leaf.py'), 'accept', str(directory), 'dGFzaw==', 'accepted'],
                                       cwd=self.world, env=self.env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, start_new_session=True)
            self.processes.append(process)
            time.sleep(1)
            self.assertIsNone(process.poll(), 'accept should be waiting on the held lock')
            (self.world / 'product').write_text('mutated while acceptance waited\n')
            fcntl.flock(lock, fcntl.LOCK_UN)
        out, err = process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0, out + err)
        self.assertIn('- [ ] task', (self.state / 'queue.md').read_text())
        self.assertFalse((directory / 'accepted.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
