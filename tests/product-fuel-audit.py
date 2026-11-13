#!/usr/bin/env python3
"""Product/value fuel, human decisions and rescan policy; no model calls."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProductFuelAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-product-fuel-', dir='/private/tmp')
        self.world = Path(self.tmp.name)
        self.home = self.world / 'home'
        self.home.mkdir()
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'CODEXC_FUEL_RECHECK': '3600'}
        self.env.pop('CODEXC_PROMPT_IDS', None)
        self.env.pop('CODEXC_FUEL_PACKS', None)
        (self.state / 'queue.md').write_text('## ready\n- [ ] existing work\n## done\n- [x] old work\n')

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, success=True):
        result = subprocess.run([str(ROOT / 'ck'), *args], cwd=self.world,
                                env=self.env, capture_output=True, text=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_catalog_covers_product_user_and_business_value(self):
        names = {line.split('\t')[0] for line in self.cli('prompts', 'list').stdout.splitlines()}
        self.assertGreaterEqual(len(names), 32)
        self.assertTrue({'onboarding', 'accessibility', 'activation', 'conversion',
                         'data-portability', 'operating-cost', 'product-discovery'} <= names)
        prompt = self.cli('prompts', 'show', 'conversion').stdout
        self.assertIn('ck propose', prompt)
        self.assertIn('不编造', prompt)

    def test_existing_full_custom_catalog_survives_builtin_expansion(self):
        directory = self.state / 'prompts'
        directory.mkdir()
        # The former 10 + 54 catalog was valid under the original 64 limit.
        for i in range(54):
            (directory / ('legacy-%02d.md' % i)).write_text('existing project recipe')
        prompt = json.loads(self.cli('prompts', 'next').stdout)
        self.assertEqual(prompt['count'], 98)

    def test_project_can_select_a_relevant_fuel_subset(self):
        self.env['CODEXC_PROMPT_IDS'] = 'onboarding,security,conversion'
        chosen = [json.loads(self.cli('prompts', 'next').stdout)['id'] for _ in range(4)]
        self.assertEqual(chosen, ['onboarding', 'security', 'conversion', 'onboarding'])
        self.env['CODEXC_PROMPT_IDS'] = 'security,unknown'
        self.assertNotEqual(self.cli('prompts', 'next', success=False).returncode, 0)

    def test_proposal_goes_to_human_review_without_stopping_ready_work(self):
        halt = self.state / 'loop.halt'
        halt.write_text('manual pause\n')
        text = 'DECISION-PRICING 选择收费方式\n证据: 当前产品已有两个导出入口\n候选: 按席位 / 按用量\n推荐: 先保留原价\n收益与代价: 待验证'
        self.cli('propose', text)
        self.cli('propose', text)  # repeating the same discovery is idempotent
        queue = (self.state / 'queue.md').read_text()
        self.assertEqual(queue.count('- [ ] DECISION-PRICING'), 1)
        self.assertEqual(halt.read_text(), 'manual pause\n')
        result = subprocess.run(['python3', str(ROOT / 'ck-leaf.py'), 'count', str(self.state / 'queue.md')],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), '1')
        self.assertIn('  证据:', queue)

    def test_proposal_cannot_overwrite_an_unfinished_acceptance(self):
        before = (self.state / 'queue.md').read_bytes()
        (self.state / 'acceptance.pending.json').write_text('{}')
        result = self.cli('propose', 'human decision', success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.state / 'queue.md').read_bytes(), before)

    def test_exhausted_fuel_rechecks_on_schedule_without_clearing_manual_pause(self):
        self.cli('prompts', 'exhaust')
        marker = self.state / 'burn-exhausted.json'
        original = json.loads(marker.read_text())
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'waiting')
        original['checked_at'] = int(time.time()) - 3601
        marker.write_text(json.dumps(original))
        halt = self.state / 'loop.halt'
        halt.write_text('operator pause')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'renewed')
        self.assertEqual(halt.read_text(), 'operator pause')
        self.cli('prompts', 'exhaust')
        value = json.loads(marker.read_text())
        value['checked_at'] = int(time.time()) - 7200
        marker.write_text(json.dumps(value))
        self.env['CODEXC_FUEL_RECHECK'] = '0'
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'waiting')

    def test_changed_repository_renews_exhausted_fuel_immediately(self):
        subprocess.run(['git', 'init', '-q'], cwd=self.world, check=True)
        (self.world / '.gitignore').write_text('.codingkeeper/\nhome/\n')
        source = self.world / 'product.txt'
        source.write_text('before')
        self.cli('prompts', 'exhaust')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'waiting')
        source.write_text('after with changed behavior')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'renewed')

    def test_morning_report_aggregates_work_decisions_and_blocks_without_writes(self):
        other = self.world / '另一个 project'
        state = other / '.codingkeeper'
        state.mkdir(parents=True)
        (state / 'queue.md').write_text('## ready\n## review-needed\n- [ ] DECISION-EXPORT choose export format\n')
        (state / 'loop.halt').write_text('real deployment credentials required')
        now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        (state / 'journal').write_text(now + ' | repaired save | accepted after 2 rounds | receipt=abc\n')
        registry = self.home / '.codingkeeper/projects'
        registry.parent.mkdir(parents=True)
        registry.write_text('# projects\n' + str(other) + '\n' + str(other) + '\n' + str(self.world) + '\n')
        before = {p: p.read_bytes() for p in [registry, state / 'queue.md', state / 'loop.halt', state / 'journal']}
        report = json.loads(self.cli('morning', '--json').stdout)
        projects = {entry['project']: entry for entry in report['projects']}
        self.assertEqual(len(projects), 2)
        entry = projects[str(other)]
        self.assertEqual(entry['accepted_count'], 1)
        self.assertEqual(entry['decision_count'], 1)
        self.assertIn('credentials', entry['halt'])
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))

    def test_morning_reports_an_invalid_project_without_hiding_other_projects(self):
        os.mkfifo(self.state / 'status.json')
        report = json.loads(self.cli('morning', '--json').stdout)
        self.assertIn('regular file', ' '.join(report['projects'][0]['errors']))


if __name__ == '__main__':
    unittest.main()
