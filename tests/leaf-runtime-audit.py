#!/usr/bin/env python3
"""Leaf value/acceptance regressions with local workers and a private HOME."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parents[1]))
SPEC = importlib.util.spec_from_file_location('leaf', ROOT / 'ck-leaf.py')
LEAF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEAF)

STUBS = r'''
pgrep() { return 1; }
register_project() { :; }
notify() { :; }
banner_set() { :; }
headless_turn() { printf 'TASK_RESULT: DONE\n' > "$2"; }
gate_run() { : > "$1"; return 0; }
review_run() { : > "$2"; printf 0; }
sleep() { touch .codingkeeper/loop.halt; }
'''


class LeafRuntimeAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ck-leaf-test-', dir='/private/tmp')
        self.world = Path(self.temp.name)
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        self.queue = self.state / 'queue.md'
        self.queue.write_text('## ready\n- [ ] task\n')
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.world / 'home'),
                    'CODEX_HOME': str(self.world / 'home/.codex'), 'TMPDIR': '/private/tmp',
                    'CODEXC_ACTIVE_WINDOW': '', 'CODEXC_LOOP_NOTIFY': '0', 'CODEXC_NOTIFY': '0', 'CODEXC_LOOP_IDLE': '0',
                    'CODEXC_AUTO_RESUME': '0', 'CODEXC_BANNER': '0', 'CODEXC_HEADLESS_CMD': 'true',
                    'CODEXC_REVIEW_PARALLEL': '0', 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_AUTHOR_NAME': 'Audit', 'GIT_AUTHOR_EMAIL': 'audit@example.invalid',
                    'GIT_COMMITTER_NAME': 'Audit', 'GIT_COMMITTER_EMAIL': 'audit@example.invalid'}
        (self.world / 'home').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def shell(self, body, script='codexc-headless', stubs=True, **env):
        source = (ROOT / script).read_text()
        if script == 'codexc-headless':
            source = source[:source.rindex('\ncase "${1:-}" in')]
        else:
            source = source.rsplit('# ---- dispatch', 1)[0]
        return subprocess.run(['/bin/bash', '-c', source + '\n' + (STUBS if stubs else '') + '\n' + body, str(ROOT / script)],
                              cwd=self.world, env=self.env | env, text=True, capture_output=True, timeout=60)

    def helper(self, *args, check=True):
        return subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), *map(str, args)], cwd=self.world,
                              env=self.env, text=True, capture_output=True, check=check, timeout=15)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.world, env=self.env, check=True,
                              text=True, capture_output=True).stdout.strip()

    def repo(self):
        self.git('init', '-q')
        (self.world / '.gitignore').write_text('.codingkeeper/\nhome/\n')
        (self.world / 'product.txt').write_text('good\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')

    def test_oversize_source_is_hashed_without_blob_and_does_not_block_acceptance(self):
        # 2026-11-12 实证: vendored 大数据文件 (tessdata 类 19.2 MiB) 触发
        # 16 MiB/file 预算 raise → 该炉永远 "leaf baseline failed" 停炉。
        # 修复后大文件流式哈希照记 (blob: False), 验收资格与证据体积解耦。
        self.repo()
        big = self.world / 'public' / 'tessdata.gz'
        big.parent.mkdir()
        with big.open('wb') as fh:
            for _ in range(17):          # 17 MiB > 16 MiB/file 预算
                fh.write(b'\x90' * (1024 * 1024))
        self.env['CODEXC_REQUIRE_GATE'] = '1'
        result = self.helper('begin', 'dGFzaw==', check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        directory = Path(result.stdout.strip())
        baseline = json.loads((directory / 'baseline.json').read_text())
        entry = baseline['files']['public/tessdata.gz']
        self.assertFalse(entry.get('blob', True), '大文件只记哈希, 内容不进证据')
        self.assertEqual(entry['size'], 17 * 1024 * 1024)
        self.assertTrue(entry['sha256'], '完整性哈希必须照记')
        oversize_blobs = [p for p in (directory / 'blobs').iterdir()
                          if p.stat().st_size > 16 * 1024 * 1024]
        self.assertEqual(oversize_blobs, [], '超限内容不得拷贝进证据')
        product_sha = baseline['files']['product.txt']['sha256']
        self.assertTrue((directory / 'blobs' / product_sha).exists() or
                        ((self.state / 'evidence' / '.blobs' / product_sha).exists()),
                        '小文件 blob 照常存证')


    def test_headless_park_preserves_an_existing_manual_halt(self):
        halt = self.state / 'loop.halt'
        halt.write_text('operator pause\n')
        result = self.shell('park "automatic failure" "model quota exhausted"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(halt.read_text(), 'operator pause\n')

    def budget_sources(self):
        self.repo()
        for i in range(8):
            with (self.world / ('a%02d.bin' % i)).open('wb') as stream:
                stream.write(bytes([i]))
                overhead = sum((self.world / name).stat().st_size for name in ('.gitignore', 'product.txt'))
                stream.truncate(16 * 1024 * 1024 - (overhead if i == 7 else 0))
        (self.world / 'zz.txt').write_text('before\n')
        return Path(self.helper('begin', 'dGFzaw==').stdout.strip())

    def test_snapshot_blob_budget_includes_the_next_file(self):
        directory = self.budget_sources()
        baseline = json.loads((directory / 'baseline.json').read_text())
        stored = sum(item.get('size', 0) for item in baseline['files'].values()
                     if item.get('blob', True))
        self.assertLessEqual(stored, 128 * 1024 * 1024)

    def test_small_hash_only_change_can_reach_verified_acceptance(self):
        directory = self.budget_sources()
        (self.world / 'zz.txt').write_text('after\n')
        result = self.helper('candidate', directory, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate = json.loads((directory / 'candidate.json').read_text())
        self.assertIn('sha256', candidate['files']['zz.txt'])
        self.helper('verify', directory)
        self.helper('accept', directory, 'dGFzaw==', 'accepted')
        self.assertIn('- [x] task', self.queue.read_text())

    def test_blob_storage_changes_are_not_source_changes(self):
        self.repo()
        directory = Path(self.helper('begin', 'dGFzaw==').stdout.strip())
        manifest = json.loads((directory / 'baseline.json').read_text())
        manifest['files']['product.txt']['blob'] = False
        (directory / 'baseline.json').write_text(json.dumps(manifest))
        self.assertEqual(self.helper('changed', directory).stdout.strip(), '0')
        self.helper('candidate', directory)
        self.assertIn('Changed paths: []', (directory / 'changes.diff').read_text())

    def test_existing_dirty_and_empty_commit_do_not_count_as_burn(self):
        self.repo()
        (self.world / 'product.txt').write_text('preexisting user edit\n')
        self.queue.write_text('## ready\n')
        result = self.shell(r'''
turns=0
headless_turn() {
    turns=$((turns+1)); [ "$turns" -lt 4 ] || exit 88
    git commit --allow-empty -qm empty
    printf 'TASK_RESULT: DONE (idle)\n' > "$2"
}
run_runner
printf 'turns=%s' "$turns"
''', CODEXC_LOOP_IDLE='1', CODEXC_PROMPT_ROTATION='0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('turns=2', result.stdout)
        self.assertFalse((self.state / 'journal').exists())
        self.assertTrue((self.state / 'loop.halt').exists())

    def test_empty_submodule_is_rejected_instead_of_snapshotting_parent(self):
        self.repo()
        head = self.git('rev-parse', 'HEAD')
        self.git('update-index', '--add', '--cacheinfo', '160000,' + head + ',module')
        self.git('commit', '-qm', 'add uninitialized module')
        (self.world / 'module').mkdir()
        result = self.helper('begin', 'dGFzaw==', check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('submodule', result.stderr)

    def test_initialized_submodule_is_snapshotted_and_hidden_untracked_file_rejected(self):
        self.repo()
        self.git('init', '-q', 'module')
        (self.world / 'module/source.txt').write_text('module content\n')
        self.git('-C', 'module', 'add', 'source.txt')
        self.git('-C', 'module', 'commit', '-qm', 'module baseline')
        head = self.git('-C', 'module', 'rev-parse', 'HEAD')
        self.git('update-index', '--add', '--cacheinfo', '160000,' + head + ',module')
        self.git('commit', '-qm', 'add initialized module')
        directory = Path(self.helper('begin', 'dGFzaw==').stdout.strip())
        baseline = json.loads((directory / 'baseline.json').read_text())
        self.assertEqual(baseline['files']['module']['kind'], 'gitlink')
        self.assertEqual((directory / 'blobs' / baseline['files']['module']['sha256']).read_text().strip(), head)
        self.git('-C', 'module', 'config', 'status.showUntrackedFiles', 'no')
        (self.world / 'module/hidden.txt').write_text('unverified module change\n')
        result = self.helper('candidate', directory, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dirty submodule', result.stderr)

    def test_committed_leaf_has_exact_diff_and_keeps_original_baseline(self):
        self.repo()
        original = self.git('rev-parse', 'HEAD')
        directory = self.helper('begin', 'dGFzaw==').stdout.strip()
        (self.world / 'product.txt').write_text('leaf change\n')
        self.git('add', 'product.txt'); self.git('commit', '-qm', 'leaf')
        self.assertEqual(self.helper('begin', 'dGFzaw==').stdout.strip(), directory)
        self.helper('candidate', directory)
        baseline = json.loads((Path(directory) / 'baseline.json').read_text())
        self.assertEqual(baseline['head'], original)
        self.assertIn('+leaf change', (Path(directory) / 'changes.diff').read_text())
        self.assertNotEqual(original, json.loads((Path(directory) / 'candidate.json').read_text())['head'])

    def test_review_candidate_mutation_cannot_accept(self):
        self.repo()
        result = self.shell(r'''
review_run() { printf 'broken\n' > product.txt; : > "$2"; printf 0; }
run_runner
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- [ ] task', self.queue.read_text())
        self.assertFalse((self.state / 'journal').exists())
        self.assertTrue((self.state / 'loop.halt').exists())

    def test_review_index_only_mutation_cannot_accept(self):
        self.repo()
        (self.world / 'product.txt').write_text('preexisting dirty content\n')
        result = self.shell(r'''
review_run() { git add product.txt; : > "$2"; printf 0; }
run_runner
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- [ ] task', self.queue.read_text())
        self.assertFalse((self.state / 'journal').exists())
        self.assertTrue((self.state / 'loop.halt').exists())

    def test_journal_failure_restores_queue_and_retains_transaction(self):
        (self.state / 'journal').mkdir()
        result = self.shell('run_runner')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- [ ] task', self.queue.read_text())
        self.assertTrue((self.state / 'acceptance.pending.json').exists())
        self.assertTrue((self.state / 'loop.halt').exists())

    def test_recovery_after_queue_write_is_idempotent_and_repairs_partial_line(self):
        directory = self.helper('begin', 'dGFzaw==').stdout.strip()
        self.helper('candidate', directory)
        (self.state / 'journal').mkdir()
        self.helper('accept', directory, 'dGFzaw==', 'accepted', check=False)
        tx = json.loads((self.state / 'acceptance.pending.json').read_text())
        (self.state / 'journal').rmdir()
        # Simulate a kill after queue publication and a partial journal append.
        self.queue.write_bytes(base64.b64decode(tx['after']))
        (self.state / 'journal').write_text(tx['line'][:35])
        self.helper('recover'); self.helper('recover')
        journal = (self.state / 'journal').read_text()
        self.assertEqual(journal.splitlines(keepends=True).count(tx['line']), 1)
        self.assertIn('- [x] task', self.queue.read_text())
        self.assertTrue((Path(directory) / 'accepted.json').exists())
        self.assertFalse((self.state / 'acceptance.pending.json').exists())

    def test_actual_partial_append_failure_rolls_back_and_recovers(self):
        directory = self.helper('begin', 'dGFzaw==').stdout.strip()
        self.helper('candidate', directory)
        fault = r'''
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('leaf', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
original = os.write
calls = 0
def failing(fd, data):
    global calls
    calls += 1
    if calls == 1: return original(fd, data[:11])
    raise OSError('injected full disk')
os.write = failing
try:
    m.accept(__import__('pathlib').Path(sys.argv[2]), 'dGFzaw==', 'accepted')
except OSError:
    print('injected failure caught')
finally:
    os.write = original
'''
        result = subprocess.run(['python3', '-c', fault, str(ROOT / 'ck-leaf.py'), directory],
                                cwd=self.world, env=self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('injected failure caught', result.stdout)
        self.assertIn('- [ ] task', self.queue.read_text())
        tx = json.loads((self.state / 'acceptance.pending.json').read_text())
        self.helper('recover'); self.helper('recover')
        self.assertEqual((self.state / 'journal').read_text().splitlines(keepends=True).count(tx['line']), 1)
        self.assertIn('- [x] task', self.queue.read_text())

    def test_tui_journal_failure_preserves_pending_leaf(self):
        (self.state / 'journal').mkdir()
        result = self.shell(r'''
sleep() { :; }
pane_idle() { return 0; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() { iterations=$((iterations+1)); [ "$iterations" -lt 8 ]; }
feed_msg() { printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE"}}' >> rollout.jsonl; }
: > rollout.jsonl
run_driver audit
''', script='codexc-loop')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- [ ] task', self.queue.read_text())
        self.assertTrue((self.state / 'loop.halt').exists())

    def test_queue_edits_conflict_with_recovery_without_being_overwritten(self):
        directory = self.helper('begin', 'dGFzaw==').stdout.strip()
        self.helper('candidate', directory)
        (self.state / 'journal').mkdir()
        self.helper('accept', directory, 'dGFzaw==', 'accepted', check=False)
        self.queue.write_text('## ready\n- [ ] human changed contract\n')
        result = self.helper('recover', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('human changed contract', self.queue.read_text())

    def test_multiline_contract_and_checkbox_spacing_roundtrip(self):
        self.queue.write_text('## ready\n- [ ]  task\n  目标: complete outcome\n  验收: test evidence\n- [ ] next\n')
        line = self.helper('next', self.queue).stdout.strip()
        task = base64.b64decode(line.split('\t')[1]).decode()
        self.assertEqual(task, 'task\n目标: complete outcome\n验收: test evidence')
        result = self.helper('mark', self.queue, line.split('\t')[1])
        self.assertEqual(result.stdout.strip(), 'marked')
        self.assertIn('- [x]  task', self.queue.read_text())
        self.assertEqual(base64.b64decode(self.helper('next', self.queue).stdout.split('\t')[1]).decode(), 'next')

    def test_invalid_queue_never_enters_burn(self):
        for data in (b'## ready\n- [ ] bad\xff', b'no section\n', b'## ready\n- [??] bad\n', b'## ready\n\0', b'## ready\n- [ ]\n'):
            self.queue.write_bytes(data)
            (self.state / 'loop.halt').unlink(missing_ok=True)
            result = self.shell(r'''
headless_turn() { touch worker-was-called; }
run_runner
''', CODEXC_LOOP_IDLE='1')
            self.assertFalse((self.world / 'worker-was-called').exists(), result.stderr)
            self.assertTrue((self.state / 'loop.halt').exists())

    def test_code_fence_examples_are_not_tasks(self):
        self.queue.write_text('## ready\n```md\n- [ ] example\n```\n- [ ] actual\n')
        task = base64.b64decode(self.helper('next', self.queue).stdout.split('\t')[1]).decode()
        self.assertEqual(task, 'actual')

    def test_missing_or_placeholder_required_gate_consumes_no_worker(self):
        for gate in (None, '#!/bin/bash\n# CK_GATE_PLACEHOLDER=1\necho placeholder\nexit 0\n', '#!/bin/bash\necho "(gate placeholder — 放入真实测试命令)"\nexit 0\n'):
            if gate is not None:
                (self.state / 'gate.sh').write_text(gate)
            (self.state / 'loop.halt').unlink(missing_ok=True)
            result = self.shell('headless_turn() { touch worker-was-called; }\nrun_runner', CODEXC_REQUIRE_GATE='1')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.world / 'worker-was-called').exists())
            self.assertTrue((self.state / 'loop.halt').exists())

    def test_empty_queue_status_is_idle(self):
        self.queue.write_text('## ready\n')
        self.shell('run_runner')
        status = json.loads((self.state / 'status.json').read_text())
        self.assertEqual(status['phase'], 'idle')
        self.assertFalse(status['active'])

    def test_nonterminal_done_text_is_not_completion(self):
        (self.world / 'output').write_text('Tests fail; I will use TASK_RESULT: DONE after fixing them.\n')
        result = self.shell('result_marker output')
        self.assertEqual(result.stdout, 'none')

    def test_diff_rendering_is_bounded_and_symlink_target_is_not_read(self):
        self.repo()
        (self.world / 'link').symlink_to('/does/not/exist')
        directory = self.helper('begin', 'dGFzaw==').stdout.strip()
        (self.world / 'product.txt').write_text('changed\n' * 100000)
        self.helper('candidate', directory)
        changes = (Path(directory) / 'changes.diff').read_text()
        self.assertIn('Diff omitted for bounded rendering', changes)
        self.assertLess(len(changes), 5000)
        self.assertEqual(json.loads((Path(directory) / 'baseline.json').read_text())['files']['link']['kind'], 'symlink')

    def assert_process_stopped(self, pid):
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
        self.assertTrue(not result.stdout.strip() or result.stdout.strip().startswith('Z'), result.stdout)

    def test_successful_review_reaps_orphan_group(self):
        result = self.shell(r'''
CODEXC_REVIEW_CMD='sleep 45 >/dev/null 2>&1 & echo $! > .codingkeeper/orphan.pid; echo "BUGS: 0"'
review_run task .codingkeeper/review
''', stubs=False)
        self.assertEqual(result.stdout, '0', result.stderr)
        self.assert_process_stopped(int((self.state / 'orphan.pid').read_text()))

    def test_timed_out_review_reaps_orphan_group(self):
        result = self.shell(r'''
CODEXC_REVIEW_TIMEOUT=1
CODEXC_REVIEW_CMD='sleep 45 >/dev/null 2>&1 & echo $! > .codingkeeper/orphan.pid; sleep 45'
review_run task .codingkeeper/review
''', stubs=False)
        self.assertEqual(result.stdout, 'timeout', result.stderr)
        self.assert_process_stopped(int((self.state / 'orphan.pid').read_text()))

    def test_runner_termination_reaps_active_review_group(self):
        source = (ROOT / 'codexc-headless').read_text()
        source = source[:source.rindex('\ncase "${1:-}" in')]
        body = r'''
pgrep() { return 1; }
register_project() { :; }
notify() { :; }
banner_set() { :; }
headless_turn() { printf 'TASK_RESULT: DONE\n' > "$2"; }
gate_run() { : > "$1"; return 0; }
CODEXC_REVIEW_CMD='sleep 45 >/dev/null 2>&1 & echo $! > .codingkeeper/orphan.pid; sleep 45'
run_runner
'''
        process = subprocess.Popen(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-headless')],
                                   cwd=self.world, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not (self.state / 'orphan.pid').exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue((self.state / 'orphan.pid').exists())
            pid = int((self.state / 'orphan.pid').read_text())
            process.terminate()
            process.communicate(timeout=5)
            self.assert_process_stopped(pid)
        finally:
            if process.poll() is None:
                process.kill(); process.communicate()


if __name__ == '__main__':
    unittest.main(verbosity=2)
