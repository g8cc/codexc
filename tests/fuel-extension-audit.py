#!/usr/bin/env python3
"""Fuel extension regressions, isolated project profiles; never model requests."""
import json
import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FuelExtensionAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-fuel-extension-', dir='/private/tmp')
        self.world = Path(self.tmp.name)
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        self.env = {**os.environ, 'HOME': str(self.world / 'home')}
        for name in ('CODEXC_PROMPT_IDS', 'CODEXC_FUEL_PACKS'):
            self.env.pop(name, None)
        (self.state / 'queue.md').write_text('## ready\n## review-needed\n')

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, success=True):
        result = subprocess.run([str(ROOT / 'ck'), *args], cwd=self.world,
                                env=self.env, capture_output=True, text=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_successful_add_remains_usable_with_selected_catalog(self):
        directory = self.state / 'prompts'; directory.mkdir()
        for i in range(96):
            (directory / ('existing-%03d.md' % i)).write_text('existing valid recipe')
        self.env['CODEXC_PROMPT_IDS'] = 'security'
        (self.world / 'new.md').write_text('new verified recovery direction')
        self.cli('prompts', 'add', 'new-recovery', '--file', 'new.md')
        self.cli('prompts', 'next')

    def test_selection_does_not_hide_prompt_inspection(self):
        self.env['CODEXC_PROMPT_IDS'] = 'security'
        self.assertIn('首次使用', self.cli('prompts', 'show', 'onboarding').stdout)

    def test_rephrased_pending_decision_id_cannot_duplicate(self):
        self.cli('propose', 'DECISION-PRICING 收费取舍\n证据: 初版分析')
        before = (self.state / 'queue.md').read_bytes()
        result = self.cli('propose', 'DECISION-PRICING 收费取舍\n证据: 换一种表述', success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already pending', result.stderr)
        self.assertEqual((self.state / 'queue.md').read_bytes(), before)

    def test_morning_marks_future_timestamp_stale_and_accepts_numeric_fresh(self):
        for ts, stale in ((int(time.time()) + 3600, True), (time.time(), False)):
            with self.subTest(ts=ts):
                (self.state / 'status.json').write_text(json.dumps({'ts': ts, 'phase': 'waiting_fuel'}))
                output = self.cli('morning', '--project', str(self.world)).stdout
                self.assertEqual('状态已陈旧' in output, stale)

    def test_catalog_change_renews_active_sweep(self):
        self.cli('prompts', 'next')
        (self.world / 'new.md').write_text('new verified recovery direction')
        self.cli('prompts', 'add', 'new-recovery', '--file', 'new.md')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'renewed')
        self.assertEqual(json.loads(self.cli('prompts', 'next').stdout)['id'], 'correctness')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'ready')

    def test_reserved_direction_is_durable_until_completion_and_completion_is_idempotent(self):
        self.env['CODEXC_PROMPT_IDS'] = 'correctness,security'
        first = json.loads(self.cli('prompts','next','--reserve').stdout)
        second = json.loads(self.cli('prompts','next','--reserve').stdout)
        self.assertEqual((first['id'], first['token']), (second['id'], second['token']))
        cursor = self.state / 'burn-cursor.json'
        before = cursor.read_bytes()
        rejected = self.cli('prompts','complete','0'*32,success=False)
        self.assertNotEqual(rejected.returncode,0)
        self.assertEqual(cursor.read_bytes(),before)
        self.cli('prompts','complete',first['token'])
        inode = cursor.stat().st_ino
        self.cli('prompts','complete',first['token'])
        self.assertEqual(cursor.stat().st_ino,inode)
        self.assertEqual(json.loads(self.cli('prompts','next','--reserve').stdout)['id'],'security')

    def test_general_and_domain_catalogs_are_separate_and_inspection_is_read_only(self):
        core = self.cli('prompts', 'list').stdout
        self.assertEqual(len(core.splitlines()), 44)
        self.assertNotIn('rag-citations', core)
        all_fuel = self.cli('prompts', 'list', '--all').stdout
        self.assertEqual(len(all_fuel.splitlines()), 129)
        info = json.loads(self.cli('prompts', 'packs', '--json').stdout)
        self.assertEqual((info['core_count'], info['domain_count'], len(info['packs'])), (44, 85, 17))
        self.assertFalse(any(item['enabled'] for item in info['packs']))
        self.assertIn('适用条件', self.cli('prompts', 'show', 'rag-citations').stdout)
        self.assertFalse((self.state / 'fuel-packs.json').exists())
        self.assertFalse((self.state / 'burn-cursor.json').exists())

    def test_enable_disable_persists_composed_domains_and_preserves_halt_and_queue(self):
        halt = self.state / 'loop.halt'; halt.write_text('operator pause')
        queue = (self.state / 'queue.md').read_bytes()
        self.cli('prompts', 'enable', 'finance', 'retrieval')
        profile = self.state / 'fuel-packs.json'
        before = profile.read_bytes(); inode = profile.stat().st_ino
        self.cli('prompts', 'enable', 'finance')
        self.assertEqual(profile.read_bytes(), before)
        self.assertEqual(profile.stat().st_ino, inode, 'idempotent enable does not rewrite state')
        self.assertEqual(json.loads(before)['enabled'], ['finance', 'retrieval'])
        self.assertEqual(profile.stat().st_mode & 0o777, 0o600)
        listed = self.cli('prompts', 'list').stdout
        self.assertEqual(len(listed.splitlines()), 54)
        self.assertIn('finance-amounts', listed)
        self.assertIn('rag-citations', listed)
        self.cli('prompts', 'disable', 'finance')
        self.assertNotIn('finance-amounts', self.cli('prompts', 'list').stdout)
        self.assertIn('rag-citations', self.cli('prompts', 'list').stdout)
        self.assertEqual(halt.read_text(), 'operator pause')
        self.assertEqual((self.state / 'queue.md').read_bytes(), queue)

    def test_invalid_pack_or_profile_fails_without_replacing_existing_state(self):
        self.cli('prompts', 'enable', 'finance')
        profile = self.state / 'fuel-packs.json'
        before = profile.read_bytes()
        result = self.cli('prompts', 'enable', 'retrieval', 'unknown', success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(profile.read_bytes(), before)
        for value in ({'version': True, 'enabled': []}, {'version': 1, 'enabled': ['finance', 'finance']},
                      {'version': 1, 'enabled': ['unknown']}, {'version': 1, 'enabled': [None]}):
            with self.subTest(profile=value):
                profile.write_text(json.dumps(value))
                invalid = profile.read_bytes()
                self.assertNotEqual(self.cli('prompts', 'next', success=False).returncode, 0)
                self.assertNotEqual(self.cli('prompts', 'enable', 'retrieval', success=False).returncode, 0)
                self.assertEqual(profile.read_bytes(), invalid)

    def test_profile_fifo_and_symlink_do_not_hang_or_overwrite_targets(self):
        profile = self.state / 'fuel-packs.json'
        os.mkfifo(profile)
        self.assertNotEqual(self.cli('prompts', 'next', success=False).returncode, 0)
        profile.unlink()
        target = self.world / 'protected.json'; target.write_text('{"version":1,"enabled":[]}')
        profile.symlink_to(target)
        before = target.read_bytes()
        self.assertNotEqual(self.cli('prompts', 'enable', 'finance', success=False).returncode, 0)
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue(profile.is_symlink())

    def test_concurrent_pack_updates_use_acceptance_lock_and_keep_all_writers(self):
        names = ['finance', 'retrieval', 'saas', 'commerce', 'content', 'automation']
        processes = []
        with (self.state / 'acceptance.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for name in names:
                processes.append(subprocess.Popen([str(ROOT / 'ck'), 'prompts', 'enable', name],
                                                   cwd=self.world, env=self.env, stdout=subprocess.PIPE,
                                                   stderr=subprocess.PIPE, text=True))
            time.sleep(.3)
            try:
                self.assertTrue(all(process.poll() is None for process in processes))
                self.assertFalse((self.state / 'fuel-packs.json').exists())
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                for process in processes:
                    out, err = process.communicate(timeout=15)
                    self.assertEqual(process.returncode, 0, out + err)
        self.assertEqual(set(json.loads((self.state / 'fuel-packs.json').read_text())['enabled']), set(names))

    def test_environment_override_and_explicit_domain_selection_do_not_rewrite_profile(self):
        self.cli('prompts', 'enable', 'developer-tools')
        profile = self.state / 'fuel-packs.json'; before = profile.read_bytes()
        self.env['CODEXC_FUEL_PACKS'] = 'finance'
        listed = self.cli('prompts', 'list').stdout
        self.assertIn('finance-amounts', listed)
        self.assertNotIn('dev-protocols', listed)
        self.env['CODEXC_FUEL_PACKS'] = ''
        self.assertEqual(len(self.cli('prompts', 'list').stdout.splitlines()), 44)
        self.env['CODEXC_PROMPT_IDS'] = 'rag-citations,finance-amounts'
        first = json.loads(self.cli('prompts', 'next').stdout)
        second = json.loads(self.cli('prompts', 'next').stdout)
        self.assertEqual((first['id'], second['id'], first['count']), ('rag-citations', 'finance-amounts', 2))
        self.assertIn('领域: retrieval', first['prompt'])
        self.assertEqual(profile.read_bytes(), before)

    def test_custom_domain_override_stays_active_when_pack_disabled(self):
        (self.world / 'custom.md').write_text('project-specific citation acceptance')
        self.cli('prompts', 'add', 'rag-citations', '--file', 'custom.md')
        self.assertIn('rag-citations', self.cli('prompts', 'list').stdout)
        self.cli('prompts', 'enable', 'retrieval')
        self.assertEqual(len(self.cli('prompts', 'list').stdout.splitlines()), 49)
        self.assertIn('project-specific', self.cli('prompts', 'show', 'rag-citations').stdout)
        self.cli('prompts', 'disable', 'retrieval')
        self.assertEqual(len(self.cli('prompts', 'list').stdout.splitlines()), 45)
        self.assertIn('rag-citations', self.cli('prompts', 'list').stdout)

    def test_full_custom_catalog_with_all_domains_fits_and_filter_cannot_bypass_capacity(self):
        directory = self.state / 'prompts'; directory.mkdir()
        for i in range(128):
            (directory / ('custom-%03d.md' % i)).write_text('existing project direction')
        names = [item['id'] for item in json.loads(self.cli('prompts', 'packs', '--json').stdout)['packs']]
        self.cli('prompts', 'enable', *names)
        self.assertEqual(json.loads(self.cli('prompts', 'next').stdout)['count'], 257)
        # Both runners consume this real TSV/base64 adapter, not the JSON CLI.
        body = r'''
set -eu
. "$1/ck-common.sh"
IDLE_PROMPT_DEFAULT=improve
IDLE_PROMPT=improve
CODEXC_IDLE_PARK=2
CODEXC_PROMPT_ROTATION=1
burn_prompt_prepare
printf '%s\t%s\n' "$BURN_PROMPT_ID" "$BURN_NOOP_LIMIT"
'''
        result = subprocess.run(['/bin/bash', '-c', body, 'fuel-adapter', str(ROOT)],
                                cwd=self.world, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'reliability\t514')
        self.env['CODEXC_PROMPT_IDS'] = 'security'
        (self.world / 'new.md').write_text('extra direction')
        result = self.cli('prompts', 'add', 'overflow', '--file', 'new.md', success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((directory / 'overflow.md').exists())
        self.cli('prompts', 'next')

    def test_concurrent_custom_additions_cannot_overfill_last_slot(self):
        directory = self.state / 'prompts'; directory.mkdir()
        for i in range(127):
            (directory / ('custom-%03d.md' % i)).write_text('existing project direction')
        (self.world / 'new.md').write_text('extra direction')
        self.env['CODEXC_PROMPT_IDS'] = 'security'
        processes = [subprocess.Popen([str(ROOT / 'ck'), 'prompts', 'add', name, '--file', 'new.md'],
                                      cwd=self.world, env=self.env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for name in ('one', 'two')]
        codes = []
        for process in processes:
            process.communicate(timeout=15); codes.append(process.returncode)
        self.assertEqual(sorted(codes), [0, 2])
        self.assertEqual(len(list(directory.glob('*.md'))), 128)
        self.cli('prompts', 'next')

    def test_order_change_and_between_call_profile_change_renew_sweeps(self):
        self.env['CODEXC_PROMPT_IDS'] = 'security,onboarding'
        self.cli('prompts', 'next')
        self.env['CODEXC_PROMPT_IDS'] = 'onboarding,security'
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'renewed')
        self.assertEqual(json.loads(self.cli('prompts', 'next').stdout)['id'], 'onboarding')
        self.env.pop('CODEXC_PROMPT_IDS')
        self.cli('prompts', 'available'); self.cli('prompts', 'next')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'ready')
        self.cli('prompts', 'enable', 'finance')
        self.cli('prompts', 'next')  # change happened after available, before next
        self.cli('prompts', 'exhaust')
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'renewed')
        self.assertFalse((self.state / 'burn-exhausted.json').exists())
        self.assertEqual(self.cli('prompts', 'available').stdout.strip(), 'ready')

    def test_legacy_cursor_is_compatible_and_bad_signature_is_preserved(self):
        cursor = self.state / 'burn-cursor.json'
        cursor.write_text('{"next":2}')
        self.assertEqual(json.loads(self.cli('prompts', 'next').stdout)['id'], 'security')
        cursor.write_text('{"next":2,"catalog":"invalid"}')
        before = cursor.read_bytes()
        self.assertNotEqual(self.cli('prompts', 'available', success=False).returncode, 0)
        self.assertEqual(cursor.read_bytes(), before)

    def test_profile_updates_preserve_project_selection_notes(self):
        profile = self.state / 'fuel-packs.json'
        value = {'version': 1, 'enabled': ['finance'], 'notes': {'finance': 'src/ledger.py already implements accounting'}}
        profile.write_text(json.dumps(value))
        self.cli('prompts', 'enable', 'retrieval')
        self.assertEqual(json.loads(profile.read_text())['notes'], value['notes'])

    def test_invalid_exhaustion_marker_cannot_partially_acknowledge_new_sweep(self):
        self.cli('prompts', 'next')
        (self.world / 'new.md').write_text('new recovery direction')
        self.cli('prompts', 'add', 'new-recovery', '--file', 'new.md')
        (self.state / 'burn-exhausted.json').write_text('{"catalog":"old","checked_at":"invalid"}')
        cursor = self.state / 'burn-cursor.json'; before = cursor.read_bytes()
        self.assertNotEqual(self.cli('prompts', 'available', success=False).returncode, 0)
        self.assertEqual(cursor.read_bytes(), before)

    def test_morning_exposes_configured_domains_and_profile_errors_without_writes(self):
        self.cli('prompts', 'enable', 'learning', 'media')
        profile = self.state / 'fuel-packs.json'; before = profile.read_bytes()
        result = json.loads(self.cli('morning', '--json', '--project', str(self.world)).stdout)['projects'][0]
        self.assertEqual(result['configured_packs'], ['learning', 'media'])
        self.assertIn('配置领域', self.cli('morning', '--project', str(self.world)).stdout)
        self.assertEqual(profile.read_bytes(), before)
        profile.write_text('{"version":1,"enabled":["unknown"]}')
        report = json.loads(self.cli('morning', '--json', '--project', str(self.world)).stdout)
        self.assertTrue(report['projects'][0]['errors'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
