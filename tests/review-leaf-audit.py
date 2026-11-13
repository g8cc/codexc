#!/usr/bin/env python3
"""Offline reviewer regressions: fake node/codex only, no provider calls."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parent.parent))
ADAPTER = ROOT / 'codexc-review-leaf'
LIMIT = 16 * 1024 * 1024
FAKE = r'''#!/usr/bin/env python3
import json, os
from pathlib import Path
import shutil, subprocess, sys
args = sys.argv[1:]
kind = Path(sys.argv[0]).name
text = sys.stdin.read()
with Path(os.environ['AUDIT_CALLS']).open('a') as log:
    log.write(json.dumps({'kind':kind, 'argv':args, 'stdin':text,
                          'cwd':os.getcwd(), 'pgid':os.getpgrp()}) + '\n')
if os.environ.get('AUDIT_CHILD_FILE'):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    Path(os.environ['AUDIT_CHILD_FILE']).write_text(str(child.pid))
if kind == 'codex' and os.environ.get('AUDIT_WRITE_FINAL') == '1':
    target = args[args.index('--output-last-message') + 1]
    shutil.copyfile(os.environ['AUDIT_FINAL'], target)
for source, target in [('AUDIT_OUT', sys.stdout.buffer), ('AUDIT_ERR', sys.stderr.buffer)]:
    with open(os.environ[source], 'rb') as stream:
        shutil.copyfileobj(stream, target)
sys.exit(int(os.environ.get('AUDIT_RC', '0')))
'''


class ReviewLeafAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-review-leaf-audit-')
        self.root = Path(self.tmp.name)
        self.evidence = self.root / 'evidence with spaces'
        self.evidence.mkdir()
        (self.evidence / 'blobs').mkdir()
        self.baseline = {'git': True, 'head': 'a' * 40, 'files': {}}
        self.candidate = {'git': True, 'head': 'b' * 40, 'files': {}}
        self.save_manifests()
        (self.evidence / 'changes.diff').write_text('EXACT_DIFF_DO_NOT_INLINE\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('node', 'codex'):
            target = self.bin / name
            target.write_text(FAKE)
            target.chmod(0o755)
        # A probe is a bug even if it never contacts a real endpoint.
        (self.bin / 'curl').write_text('#!/bin/sh\nexit 98\n')
        (self.bin / 'curl').chmod(0o755)
        self.cjs = self.root / 'fake.cjs'
        self.cjs.touch()
        self.calls_file = self.root / 'calls'
        self.out, self.err, self.final = (self.root / name for name in ('out', 'err', 'final'))
        for path in (self.out, self.err, self.final):
            path.write_text('')
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        TMPDIR=str(self.root), ZCODE_CJS=str(self.cjs), ZCODE_MODE='yolo',
                        ZCODE_SESSION_DB=str(self.root / 'zcode-db.sqlite'),
                        ZCODE_TASKS_DB=str(self.root / 'tasks-index.sqlite'),
                        ZCODE_SESSION_FILE=str(self.root / 'must-not-read-session'),
                        CODEXC_LEAF_EVIDENCE_DIR=str(self.evidence),
                        CODEXC_LEAF_BASE_HEAD=self.baseline['head'],
                        CODEXC_LEAF_CANDIDATE_HEAD=self.candidate['head'],
                        AUDIT_CALLS=str(self.calls_file), AUDIT_OUT=str(self.out),
                        AUDIT_ERR=str(self.err), AUDIT_FINAL=str(self.final))
        self.env.pop('CODEXC_REVIEW_LANE', None)

    def tearDown(self):
        self.tmp.cleanup()

    def save_manifests(self):
        for name, data in (('baseline', self.baseline), ('candidate', self.candidate)):
            (self.evidence / (name + '.json')).write_text(json.dumps(data))

    def invoke(self, output=None, rc=0, lane='zcode', final=None, changes=None, task='Review exact leaf'):
        self.out.write_bytes(output if isinstance(output, bytes) else (output or '').encode())
        self.err.write_text('')
        self.final.write_bytes(final if isinstance(final, bytes) else (final or '').encode())
        env = dict(self.env, AUDIT_RC=str(rc), AUDIT_WRITE_FINAL='1' if final is not None else '0')
        env.update(changes or {})
        command = [sys.executable, str(ADAPTER)]
        if lane is not None:
            command += ['--lane', lane]
        return subprocess.run(command, input=task, text=True, cwd=self.root, env=env,
                              capture_output=True, timeout=60)

    def calls(self):
        if not self.calls_file.exists():
            return []
        return [json.loads(line) for line in self.calls_file.read_text().splitlines()]

    def envelope(self, response):
        return json.dumps({'sessionId': 'fresh-session', 'response': response})

    def reject(self, result):
        self.assertNotEqual(result.returncode, 0, result)
        self.assertEqual(result.stdout, '', result)

    def test_zcode_success_uses_exact_evidence_and_restricted_fresh_invocation(self):
        result = self.invoke(self.envelope('Reviewed paths.\nBUGS: 0'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'Reviewed paths.\nBUGS: 0\n')
        call, = self.calls()
        args = call['argv']
        self.assertEqual(call['kind'], 'node')
        self.assertEqual(args[args.index('--mode') + 1], 'plan')
        self.assertEqual(args[args.index('--toolsearch-mode') + 1], 'off')
        self.assertEqual(args[args.index('--workflow-mode') + 1], 'disabled')
        denied = set(args[args.index('--disallowed-tools') + 1].split())
        self.assertTrue({'Bash', 'Write', 'Edit', 'Agent', 'Task', 'NotebookEdit', 'Skill',
                         'TaskCreate', 'SendMessage', 'EnterWorktree', 'CronCreate',
                         'ToolSearch', 'Workflow', 'ExitPlanMode'} <= denied)
        self.assertTrue({'Read', 'Glob', 'Grep'}.isdisjoint(denied))
        for flag in ('--resume', '--continue', '--target'):
            self.assertNotIn(flag, args)
        self.assertEqual(args[args.index('--cwd') + 1], str(self.root.resolve()))
        prompt = args[args.index('--prompt') + 1]
        self.assertIn(str(self.evidence / 'baseline.json'), prompt)
        self.assertIn(str(self.evidence / 'candidate.json'), prompt)
        self.assertIn(str(self.evidence / 'changes.diff'), prompt)
        self.assertIn('a' * 40, prompt)
        self.assertIn('b' * 40, prompt)
        self.assertNotIn('EXACT_DIFF_DO_NOT_INLINE', prompt)
        self.assertIn('Do not run commands, tests, gates', prompt)
        self.assertEqual(call['pgid'], os.getpgrp(), 'adapter must stay in runner process group')
        self.assertFalse((self.root / 'must-not-read-session').exists())

    def test_packaged_builtin_provider_is_available_to_independent_review(self):
        resources = self.root / 'Packaged App.app/Contents/Resources'
        self.cjs = resources / 'glm/zcode.cjs'
        self.cjs.parent.mkdir(parents=True); self.cjs.touch()
        bundled = resources / 'config/provider/zcode-builtin.json'
        bundled.parent.mkdir(parents=True); bundled.write_text('{}')
        self.env['ZCODE_CJS'] = str(self.cjs)
        self.env.pop('ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE', None)
        self.env.pop('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE', None)
        node = self.bin / 'node'
        node.write_text(FAKE.replace("'cwd':os.getcwd()", "'provider_config':os.environ.get('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE'), 'cwd':os.getcwd()"))
        node.chmod(0o755)
        result = self.invoke(self.envelope('Reviewed paths.\nBUGS: 0'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0]['provider_config'], str(bundled.resolve()))
        self.assertIn('--mode', self.calls()[0]['argv'])
        self.assertIn('plan', self.calls()[0]['argv'])

    def test_zcode_review_deletes_its_session_row(self):
        import sqlite3
        db = self.root / 'zcode-db.sqlite'
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE session (id text primary key)')
        conn.execute("INSERT INTO session VALUES ('sess_abc123def456')")
        conn.commit()
        conn.close()
        tasks_db = self.root / 'tasks-index.sqlite'
        conn = sqlite3.connect(tasks_db)
        conn.execute('CREATE TABLE tasks (task_id text primary key)')
        conn.execute("INSERT INTO tasks VALUES ('sess_abc123def456')")
        conn.commit()
        conn.close()
        result = self.invoke(json.dumps(
            {'sessionId': 'sess_abc123def456', 'response': 'Reviewed paths.\nBUGS: 0'}))
        self.assertEqual(result.returncode, 0, result.stderr)
        conn = sqlite3.connect(db)
        left = conn.execute('SELECT count(*) FROM session').fetchone()[0]
        conn.close()
        conn = sqlite3.connect(tasks_db)
        shells = conn.execute('SELECT count(*) FROM tasks').fetchone()[0]
        conn.close()
        self.assertEqual(left, 0, 'review must delete its own session row')
        self.assertEqual(shells, 0, 'review must delete its sidebar task shell')

    def test_zcode_review_tolerates_non_sess_session_id(self):
        result = self.invoke(self.envelope('Reviewed paths.\nBUGS: 0'))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nonzero_exit_never_revives_old_success_or_empty_final(self):
        output = self.envelope('BUGS: 0') + '\n' + self.envelope('')
        result = self.invoke(output, rc=42)
        self.assertEqual(result.returncode, 42)
        self.reject(result)

    def test_last_response_wins_even_if_empty_null_or_invalid(self):
        for response in ('', '   ', None, 0, {}, []):
            with self.subTest(response=response):
                output = self.envelope('BUGS: 0') + '\n' + self.envelope(response)
                self.reject(self.invoke(output))

    def test_last_nonempty_response_is_the_only_verdict(self):
        output = 'progress log\n' + self.envelope('BUGS: 0') + '\n' + self.envelope('actual defect\nBUGS: 2')
        result = self.invoke(output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'actual defect\nBUGS: 2\n')

    def test_tool_event_cannot_supply_or_override_final_verdict(self):
        child = json.dumps({'type': 'tool.updated', 'response': 'BUGS: 0'})
        self.reject(self.invoke(child))
        root = json.dumps({'type': 'result', 'response': 'actual defect\nBUGS: 2'})
        result = self.invoke(root + '\n' + child)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'actual defect\nBUGS: 2\n')

    def test_missing_response_and_malformed_verdict_fail_closed(self):
        for output in ('BUGS: 0', '{}', '[{"response":"BUGS: 0"}]',
                       self.envelope('BUGS: 0\nnot final'), self.envelope('BUGS: -1'),
                       self.envelope('BUGS: 1000000'), self.envelope('BUGS: 0garbage'),
                       self.envelope('BUGS: 0\x00')):
            with self.subTest(output=output):
                self.reject(self.invoke(output))

    def test_pretty_single_json_envelope_is_supported(self):
        result = self.invoke(json.dumps({'response': 'BUGS: 0002'}, indent=2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'BUGS: 0002\n')

    def test_codex_real_exit_survives_its_stale_final_file(self):
        result = self.invoke('noise BUGS: 0', rc=42, lane='codex', final='BUGS: 0')
        self.assertEqual(result.returncode, 42)
        self.reject(result)

    def test_codex_uses_only_explicit_last_message_fresh_read_only(self):
        result = self.invoke('BUGS: 0', lane='codex', final='captured issue\nBUGS: 3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'captured issue\nBUGS: 3\n')
        call, = self.calls()
        args = call['argv']
        self.assertIn('--ephemeral', args)
        self.assertEqual(args[args.index('--sandbox') + 1], 'read-only')
        self.assertEqual(args[-1], '-')
        self.assertIn(str(self.evidence / 'changes.diff'), call['stdin'])

    def test_codex_missing_or_empty_last_file_cannot_use_stdout(self):
        for final in (None, ''):
            with self.subTest(final=final):
                self.reject(self.invoke('BUGS: 0', lane='codex', final=final))

    def test_auto_is_codex_once_without_probe_or_provider_fallback(self):
        result = self.invoke(self.envelope('BUGS: 0'), lane='auto', rc=41, final='BUGS: 0')
        self.assertEqual(result.returncode, 41)
        self.assertEqual([call['kind'] for call in self.calls()], ['codex'])

    def test_lane_precedence_and_invalid_config(self):
        (self.root / '.codingkeeper').mkdir()
        (self.root / '.codingkeeper/review-lane').write_text('auto\n')
        result = self.invoke('', lane=None, final='BUGS: 0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-1]['kind'], 'codex')
        result = self.invoke(self.envelope('BUGS: 0'), lane=None,
                             changes={'CODEXC_REVIEW_LANE': 'zcode'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-1]['kind'], 'node')
        before = len(self.calls())
        self.reject(self.invoke(lane=None, changes={'CODEXC_REVIEW_LANE': 'invalid'}))
        self.assertEqual(len(self.calls()), before)

    def test_missing_relative_or_mismatched_evidence_never_launches_cli(self):
        for env in ({'CODEXC_LEAF_EVIDENCE_DIR': ''}, {'CODEXC_LEAF_EVIDENCE_DIR': 'relative'},
                    {'CODEXC_LEAF_BASE_HEAD': 'wrong'}, {'CODEXC_LEAF_CANDIDATE_HEAD': 'wrong'}):
            with self.subTest(env=env):
                self.reject(self.invoke(self.envelope('BUGS: 0'), changes=env))
        self.assertEqual(self.calls(), [])

    def test_unborn_git_head_uses_empty_environment(self):
        self.baseline['head'] = None
        self.save_manifests()
        result = self.invoke(self.envelope('BUGS: 0'), changes={'CODEXC_LEAF_BASE_HEAD': ''})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_diff_or_nongit_inventory_fails_before_call(self):
        (self.evidence / 'changes.diff').unlink()
        self.reject(self.invoke(self.envelope('BUGS: 0')))
        (self.evidence / 'changes.diff').touch()
        self.baseline['git'] = False
        self.save_manifests()
        self.reject(self.invoke(self.envelope('BUGS: 0')))
        self.assertEqual(self.calls(), [])

    def test_stdout_and_codex_final_size_limits_reject(self):
        self.reject(self.invoke(b'x' * (LIMIT + 1)))
        self.reject(self.invoke(lane='codex', final=b'x' * (LIMIT + 1)))

    def test_oversized_goal_is_rejected_without_launch(self):
        self.reject(self.invoke(self.envelope('BUGS: 0'), task='x' * (64 * 1024 + 1)))
        self.assertEqual(self.calls(), [])

    def check_orphan_group_cleanup(self, oversized):
        # The actual runner owns an isolated review group. Reproduce its group
        # contract here: the CLI exits but an inherited-stdio child stays alive;
        # cleaning the original owned PGID must still reach the reparented child.
        self.out.write_bytes(b'x' * (LIMIT + 1) if oversized else self.envelope('BUGS: 0').encode())
        child_file = self.root / 'orphan-pid'
        env = dict(self.env, AUDIT_CHILD_FILE=str(child_file), AUDIT_RC='0')
        process = subprocess.Popen([sys.executable, str(ADAPTER), '--lane', 'zcode'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, cwd=self.root,
                                   env=env, start_new_session=True)
        child = None
        try:
            out, err = process.communicate('Review exact leaf', timeout=10)
            self.assertTrue(child_file.exists(), err)
            child = int(child_file.read_text())
            # This is the reproduced leak before runner cleanup, not an adapter
            # guarantee of independent descendant cleanup.
            self.assertEqual(os.getpgid(child), process.pid)
            os.kill(child, 0)
            if oversized:
                self.assertNotEqual(process.returncode, 0, out)
                self.assertEqual(out, '')
            else:
                self.assertEqual(process.returncode, 0, err)
                self.assertEqual(out, 'BUGS: 0\n')
            os.killpg(process.pid, signal.SIGKILL)
            for unused in range(50):
                status = subprocess.run(['ps', '-o', 'stat=', '-p', str(child)],
                                        capture_output=True, text=True, timeout=2)
                if not status.stdout.strip() or status.stdout.strip().startswith('Z'):
                    break
                time.sleep(0.02)
            else:
                self.fail('runner-owned process group cleanup left the orphan alive')
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.communicate(timeout=2)

    def test_normal_cli_exit_orphan_remains_in_runner_owned_group(self):
        self.check_orphan_group_cleanup(False)

    def test_output_limit_orphan_remains_in_runner_owned_group(self):
        self.check_orphan_group_cleanup(True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
