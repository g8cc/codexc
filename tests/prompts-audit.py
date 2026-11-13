#!/usr/bin/env python3
"""Prompt rotation and live queue additions, without coding tools."""
import json
import base64
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PromptsAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-prompts-', dir='/private/tmp')
        self.world = Path(self.tmp.name)
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        self.env = dict(os.environ, HOME=str(self.world / 'home'),
                        CODEX_HOME=str(self.world / 'home/.codex'), CODEXC_LOOP_NOTIFY='0',
                        CODEXC_NOTIFY='0', CODEXC_AUTO_RESUME='0', CODEXC_ACTIVE_WINDOW='',
                        CODEXC_BANNER='0', CODEXC_PROMPT_ROTATION='1')

        self.env.pop('CODEXC_FUEL_PACKS', None)
        self.env.pop('CODEXC_PROMPT_IDS', None)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, success=True):
        result = subprocess.run([str(ROOT / 'ck'), *args], cwd=self.world,
                                env=self.env, capture_output=True, text=True, timeout=10)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_rotation_covers_all_recipes_and_survives_restarts(self):
        names = [line.split('\t')[0] for line in self.cli('prompts', 'list').stdout.splitlines()]
        self.assertEqual(len(names), 44)
        chosen = [json.loads(self.cli('prompts', 'next').stdout)['id'] for _ in names]
        self.assertEqual(chosen, names)
        self.assertEqual(json.loads(self.cli('prompts', 'next').stdout)['id'], names[0])

    def test_project_prompt_can_be_added_while_rotation_is_live(self):
        first = json.loads(self.cli('prompts', 'next').stdout)
        (self.world / 'recipe.md').write_text('检查恢复幂等性；先复现再修复。\n')
        self.cli('prompts', 'add', 'recovery', '--file', 'recipe.md')
        outputs = [json.loads(self.cli('prompts', 'next').stdout) for _ in range(45)]
        self.assertEqual(outputs[0]['id'], 'correctness')
        self.assertTrue(any(x['id'] == 'recovery' and '恢复幂等性' in x['prompt'] for x in outputs))
        self.assertEqual(first['count'], 44)
        self.assertTrue(all(x['count'] == 45 for x in outputs))

    def test_invalid_fuel_and_cursor_fail_without_destroying_existing_data(self):
        self.cli('prompts', 'next')
        cursor = self.state / 'burn-cursor.json'
        cursor.write_text('corrupt')
        self.cli('prompts', 'next', success=False)
        self.assertEqual(cursor.read_text(), 'corrupt')
        (self.world / 'recipe.md').write_text('valid')
        self.cli('prompts', 'add', '../escape', '--file', 'recipe.md', success=False)
        self.cli('prompts', 'add', 'custom', '--file', 'recipe.md')
        self.cli('prompts', 'add', 'custom', '--file', 'recipe.md', success=False)

    def test_enqueue_preserves_metacharacters_multiline_contract_and_manual_halt(self):
        (self.state / 'queue.md').write_text('## ready\n- [ ] existing\n## review-needed\n- [ ] human review\n')
        (self.state / 'queue.md').chmod(0o640)
        (self.state / 'loop.halt').write_text('operator pause\n')
        task = '修复 $(touch injected) `touch other`\n### 验收\n真实回归必须失败后变绿'
        self.cli('enqueue', task)
        text = (self.state / 'queue.md').read_text()
        self.assertIn('- [ ] existing', text)
        self.assertIn('  ### 验收\n  真实回归', text)
        self.assertLess(text.index('修复'), text.index('## review-needed'))
        self.assertFalse((self.world / 'injected').exists())
        self.assertFalse((self.world / 'other').exists())
        self.assertEqual((self.state / 'loop.halt').read_text(), 'operator pause\n')
        self.assertEqual((self.state / 'queue.md').stat().st_mode & 0o777, 0o640)

    def test_concurrent_queue_additions_are_not_lost(self):
        jobs = [subprocess.Popen([str(ROOT / 'ck'), 'enqueue', 'task ' + str(i)],
                                 cwd=self.world, env=self.env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True) for i in range(8)]
        for process in jobs:
            out, err = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, out + err)
        text = (self.state / 'queue.md').read_text()
        self.assertEqual(text.count('- [ ] task '), 8)

    def test_enqueue_roundtrips_code_indentation_and_blank_lines(self):
        task = 'implement parser\n\n```python\ndef parse():\n    return 1\n```\n\nverify result'
        self.cli('enqueue', task)
        result = subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), 'next',
                                 str(self.state / 'queue.md')], cwd=self.world,
                                capture_output=True, text=True, check=True)
        actual = base64.b64decode(result.stdout.strip().split('\t')[1]).decode()
        self.assertEqual(actual, task)
        self.cli('enqueue', task, success=False)
        self.assertEqual((self.state / 'queue.md').read_text().count('- [ ] implement parser'), 1)
        marked = subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), 'mark',
                                 str(self.state / 'queue.md'), base64.b64encode(task.encode()).decode()],
                                capture_output=True, text=True, check=True)
        self.assertEqual(marked.stdout.strip(), 'marked')
        self.assertIn('- [x] implement parser', (self.state / 'queue.md').read_text())
        self.cli('enqueue', 'preserve leading indentation\n    return 2')
        count = subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), 'count',
                                str(self.state / 'queue.md')], capture_output=True, text=True, check=True)
        self.assertEqual(count.stdout.strip(), '1')
        self.cli('enqueue', 'preserve leading indentation\n    return 2', success=False)

    def test_enqueue_refuses_pending_acceptance_and_fenced_ready_example(self):
        queue = self.state / 'queue.md'
        queue.write_text('```md\n## ready\n```\n## ready\n## done\n')
        self.cli('enqueue', '--prompt', 'correctness')
        text = queue.read_text()
        self.assertTrue(text.startswith('```md\n## ready\n```\n## ready\n- [ ]'))
        (self.state / 'acceptance.pending.json').write_text('{}')
        self.cli('enqueue', 'next task', success=False)
        self.assertEqual(queue.read_text(), text)

    def test_enqueue_cannot_shadow_unmigrated_legacy_queue(self):
        legacy = self.world / '.codexc'; legacy.mkdir()
        (legacy / 'queue.md').write_text('## ready\n- [ ] legacy pending task\n')
        self.cli('enqueue', 'new task', success=False)
        self.assertFalse((self.state / 'queue.md').exists())
        self.assertIn('legacy pending task', (legacy / 'queue.md').read_text())

    def test_enqueue_ignores_fences_inside_existing_task_contract(self):
        (self.state / 'queue.md').write_text('## ready\n- [ ] inspect malformed sample\n  ```python\n  sample without closing fence\n## done\n')
        self.cli('enqueue', 'new reachable task')
        count = subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), 'count',
                                str(self.state / 'queue.md')], capture_output=True, text=True, check=True)
        self.assertEqual(count.stdout.strip(), '2')

    def test_headless_quota_retry_keeps_the_same_fuel(self):
        (self.state / 'queue.md').write_text('## ready\n')
        source = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        body = r'''
register_project() { :; }
notify() { :; }
ck_window_check() {
    CK_WINDOW_ALLOWED=1; CK_WINDOW_REASON=allowed
    CK_WINDOW_DEADLINE=$(( $(date +%s) + 60 ))
    CK_WINDOW_NEXT_OPEN=$(( $(date +%s) + 600 ))
    return 0
}
headless_turn() {
    printf '%s\n' "$BURN_PROMPT_ID" >> selected
    if [ "$(wc -l < selected)" -eq 1 ]; then
        printf 'CK_ERROR_CLASS: quota\n' > "$2"
        return 1
    fi
    touch .codingkeeper/loop.halt
    return 125
}
sleep() { printf '1\n' > .codingkeeper/quota-until; }
run_runner
'''
        env = self.env | {'CODEXC_HEADLESS_CMD': 'true', 'CODEXC_LOOP_IDLE': '1',
                          'CODEXC_AUTO_RESUME': '1', 'CODEXC_REQUIRE_GATE': '0',
                          'CODEXC_PROMPT_IDS': 'correctness,security'}
        result = subprocess.run(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-headless')],
                                cwd=self.world, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.world / 'selected').read_text().splitlines(), ['correctness','correctness'])
        self.assertFalse((self.state / 'journal').exists())

    def test_failed_tui_feed_does_not_consume_the_fuel(self):
        (self.state / 'queue.md').write_text('## ready\n')
        source = (ROOT / 'codexc-loop').read_text().rsplit('# ---- dispatch', 1)[0]
        body = r'''
register_project() { :; }
notify() { :; }
banner_set() { :; }
sleep() { :; }
pane_idle() { return 0; }
pane_alive() { [ ! -e .codingkeeper/loop.halt ]; }
feed_turn() {
    printf '%s\n' "$BURN_PROMPT_ID" >> selected
    if [ "$(wc -l < selected)" -ge 2 ]; then touch .codingkeeper/loop.halt; fi
    return 1
}
run_driver fake-pane
'''
        env = self.env | {'CODEXC_TOOL': 'codex', 'CODEXC_LOOP_IDLE': '1', 'CODEXC_REQUIRE_GATE': '0',
                          'CODEXC_PROMPT_IDS': 'correctness,security'}
        result = subprocess.run(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-loop')],
                                cwd=self.world, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.world / 'selected').read_text().splitlines(), ['correctness','correctness'])

    def test_headless_burn_rotates_then_waits_for_fuel_without_halting(self):
        (self.state / 'queue.md').write_text('## ready\n')
        source = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        body = r'''
register_project() { :; }
notify() { :; }
headless_turn() { printf '%s\n' "$BURN_PROMPT_ID" >> selected; printf 'TASK_RESULT: DONE (idle)\n' > "$2"; }
sleep() { cp .codingkeeper/status.json waiting.json; touch .codingkeeper/loop.halt; }
run_runner
'''
        env = self.env | {'CODEXC_HEADLESS_CMD': 'true', 'CODEXC_LOOP_IDLE': '1', 'CODEXC_REQUIRE_GATE': '0',
                          'CODEXC_PROMPT_IDS': 'correctness,reliability,security'}
        result = subprocess.run(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-headless')],
                                # Twenty real queue/snapshot/status cycles spawn many
                                # Python helpers; under load they exceed 30 seconds.
                                cwd=self.world, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = (self.world / 'selected').read_text().splitlines()
        self.assertEqual(len(selected), 6)
        self.assertEqual(len(set(selected[:3])), 3)
        self.assertEqual(selected[:3], selected[3:])
        self.assertFalse((self.state / 'journal').exists())
        self.assertTrue((self.state / 'burn-exhausted.json').exists())
        self.assertFalse(json.loads((self.world / 'waiting.json').read_text())['parked'])
        self.assertEqual(json.loads((self.world / 'waiting.json').read_text())['phase'], 'waiting_fuel')

    def test_headless_uses_saved_domain_profile_without_recipe_filter(self):
        (self.state / 'queue.md').write_text('## ready\n')
        self.cli('prompts', 'enable', 'retrieval')
        # Legacy cursors can resume at a domain recipe; no selection override.
        (self.state / 'burn-cursor.json').write_text('{"next":44}')
        source = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        body = r'''
register_project() { :; }
notify() { :; }
headless_turn() {
    printf '%s\n' "$BURN_PROMPT_ID" >> selected
    printf '%s\n' "$BURN_NOOP_LIMIT" >> limits
    printf '%s\n' "$1" > last-prompt
    printf 'TASK_RESULT: DONE (idle)\n' > "$2"
    if [ "$BURN_PROMPT_ID" = correctness ]; then
        printf 'test finished\n' > .codingkeeper/loop.halt
    fi
}
run_runner
'''
        env = self.env | {'CODEXC_HEADLESS_CMD': 'true', 'CODEXC_LOOP_IDLE': '1', 'CODEXC_REQUIRE_GATE': '0'}
        result = subprocess.run(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-headless')],
                                cwd=self.world, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.world / 'selected').read_text().splitlines(),
                         ['rag-ingestion', 'rag-relevance', 'rag-citations', 'rag-access', 'rag-freshness', 'correctness'])
        self.assertEqual((self.world / 'limits').read_text().splitlines(), ['98'] * 6)
        self.assertIn('CodingKeeper 燃料: correctness', (self.world / 'last-prompt').read_text())
        self.assertFalse((self.state / 'journal').exists())

    def test_tui_burn_uses_same_recipe_rotation_and_exhaustion(self):
        (self.state / 'queue.md').write_text('## ready\n')
        (self.world / 'rollout.jsonl').touch()
        source = (ROOT / 'codexc-loop').read_text().rsplit('# ---- dispatch', 1)[0]
        body = r'''
register_project() { :; }
notify() { :; }
banner_set() { :; }
sleep() { :; }
pane_idle() { return 0; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() { iterations=$((iterations+1)); [ "$iterations" -lt 70 ] && [ ! -e .codingkeeper/loop.halt ]; }
feed_msg() {
    printf '%s\n' "$BURN_PROMPT_ID" >> selected
    printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE (idle)"}}' >> rollout.jsonl
}
run_driver fake-pane
'''
        env = self.env | {'CODEXC_TOOL': 'codex', 'CODEXC_LOOP_IDLE': '1', 'CODEXC_REQUIRE_GATE': '0',
                          'CODEXC_PROMPT_IDS': 'correctness,reliability,security'}
        result = subprocess.run(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-loop')],
                                cwd=self.world, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = (self.world / 'selected').read_text().splitlines()
        self.assertEqual(len(selected), 6)
        self.assertEqual(len(set(selected[:3])), 3)
        self.assertEqual(selected[:3], selected[3:])
        self.assertFalse((self.state / 'loop.halt').exists())
        self.assertTrue((self.state / 'burn-exhausted.json').exists())

    def test_new_prompt_wakes_exhausted_fuel_without_clearing_manual_halt(self):
        self.cli('prompts', 'exhaust')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'waiting')
        (self.state / 'loop.halt').write_text('manual pause')
        (self.world / 'recipe.md').write_text('New project recovery goal')
        self.cli('prompts', 'add', 'recovery', '--file', 'recipe.md')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'renewed')
        self.assertEqual((self.state / 'loop.halt').read_text(), 'manual pause')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'ready')

    def test_running_exhausted_headless_runner_accepts_newly_added_task(self):
        (self.state / 'queue.md').write_text('## ready\n')
        self.cli('prompts', 'exhaust')
        source = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        body = r'''
register_project() { :; }
notify() { :; }
headless_turn() {
    if [ "$task_kind" = idle ]; then touch .codingkeeper/loop.halt; return 125; fi
    printf 'TASK_RESULT: DONE\n' > "$2"
}
gate_run() { : > "$1"; return 0; }
review_run() { : > "$2"; printf 0; }
sleep() { python3 "$CK_COMMON_DIR/ck-prompts.py" enqueue 'new task' >/dev/null; }
run_runner
'''
        env = self.env | {'CODEXC_LOOP_IDLE': '1', 'CODEXC_REQUIRE_GATE': '0', 'CODEXC_HEADLESS_CMD': 'true'}
        result = subprocess.run(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-headless')],
                                cwd=self.world, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- [x] new task', (self.state / 'queue.md').read_text())
        self.assertFalse((self.state / 'burn-exhausted.json').exists())

    def test_reviewer_receives_specific_burn_goal(self):
        source = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        body = r'''
task_kind=idle
BURN_PROMPT='Prove restart recovery is idempotent under the recorded failure'
CODEXC_REVIEW_CMD='cat > captured; printf "BUGS: 0\n"'
review_run '(idle improvement)' .codingkeeper/review
'''
        result = subprocess.run(['/bin/bash', '-c', source + body, str(ROOT / 'codexc-headless')],
                                cwd=self.world, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '0')
        self.assertIn('restart recovery is idempotent', (self.world / 'captured').read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
