#!/usr/bin/env python3
"""Offline quota classification regressions against a fake ZCode process."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parent.parent
NOTICE = ("额度已领到（12,345 token），11-05 23:00 起生效，还有约 100 分钟。\n\n"
          "这是套餐的生效规则，不是报错；到点直接用即可，不用重试。")


class ZcodeQuotaAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-zcode-quota-")
        self.root = Path(self.tmp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        node = bin_dir / "node"
        node.write_text('#!/bin/bash\ncat "$AUDIT_STDOUT"\ncat "$AUDIT_STDERR" >&2\nexit "$AUDIT_EXIT"\n')
        node.chmod(0o755)
        self.cjs = self.root / "fake.cjs"
        self.cjs.touch()
        self.session = self.root / "session"
        self.session.write_text("sess_previous\n")
        self.out = self.root / "out"
        self.err = self.root / "err"
        self.env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                        ZCODE_CJS=str(self.cjs), ZCODE_SESSION_FILE=str(self.session),
                        ZCODE_SESSION_DB=str(self.root / 'absent-session-db.sqlite'),
                        AUDIT_STDOUT=str(self.out), AUDIT_STDERR=str(self.err), TMPDIR=str(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def run_worker(self, stdout, stderr="", rc=0):
        self.out.write_text(stdout)
        self.err.write_text(stderr)
        return subprocess.run([str(REPO / "codexc-zcode-worker")], input="offline test task", text=True,
                              cwd=self.root, env=dict(self.env, AUDIT_EXIT=str(rc)), capture_output=True, timeout=60)

    def response(self, text, sid="sess_previous"):
        return json.dumps(dict(sessionId=sid, response=text), ensure_ascii=False)

    def assert_error(self, result, kind):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        markers = [line for line in result.stdout.splitlines() if line.startswith("CK_ERROR_CLASS:")]
        self.assertEqual(markers, ["CK_ERROR_CLASS: " + kind])
        self.assertEqual(self.session.read_text(), "sess_previous\n")

    def test_gateway_success_notice_is_quota_and_preserves_previous_session(self):
        self.assert_error(self.run_worker(self.response(NOTICE, "sess_new")), "quota")

    def test_gateway_notice_amount_and_time_variations(self):
        for amount in ("1", "999", "1,234,567"):
            with self.subTest(amount=amount):
                text = NOTICE.replace("12,345", amount).replace("11-05 23:00", "12-31 00:01")
                self.assert_error(self.run_worker(self.response(text)), "quota")

    def test_plain_discussion_of_quota_remains_a_normal_response(self):
        text = "已修复 code 1005、1006 的额度、套餐有效期及模型覆盖检查。\nTASK_RESULT: DONE"
        result = self.run_worker(self.response(text))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, text)

    def test_quoted_notice_in_a_task_result_is_not_a_gateway_error(self):
        text = "已增加以下提示的测试：\n```\n" + NOTICE + "\n```\nTASK_RESULT: DONE"
        result = self.run_worker(self.response(text))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, text)

    def test_successful_response_containing_error_json_is_not_reclassified(self):
        text = 'Use {"code":1006,"retryable":false} in the regression fixture.\nTASK_RESULT: DONE'
        result = self.run_worker(self.response(text))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, text)

    def test_failed_code_1005_is_quota(self):
        for code in (1005, "1005"):
            with self.subTest(code=code):
                self.assert_error(self.run_worker("", json.dumps({"code": code, "msg": "not active"}), 1), "quota")

    def test_failed_code_1006_is_auth_even_when_message_mentions_quota(self):
        for code in (1006, "1006"):
            with self.subTest(code=code):
                error = json.dumps({"code": code, "msg": "模型 M 不在这个账号的套餐里（额度还剩 1,000 token）。", "retryable": False}, ensure_ascii=False)
                self.assert_error(self.run_worker(error, rc=1), "auth")

    def test_failed_cli_code_text_is_classified(self):
        self.assert_error(self.run_worker("", "gateway.ai.error: code=1006; model not covered", 1), "auth")

    def test_failed_package_validity_message_is_quota(self):
        self.assert_error(self.run_worker("", "不在套餐有效期内", 1), "quota")

    def test_unrelated_number_in_failure_is_not_a_provider_code(self):
        self.assert_error(self.run_worker("", "build failed at example1006:120", 1), "unknown")

    def test_chinese_failure_tails_remain_visible_in_utf8_locale(self):
        self.env['LC_ALL'] = 'en_US.UTF-8'
        message = '错' * 1800 + '\n真实故障：连接失败\n'
        for channel in ('stdout', 'stderr'):
            with self.subTest(channel=channel):
                result = self.run_worker(message if channel == 'stdout' else '',
                                         message if channel == 'stderr' else '', 1)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('CK_ERROR_CLASS: unknown', result.stdout)
                self.assertIn('真实故障：连接失败', result.stdout)
                self.assertNotIn('Illegal byte sequence', result.stdout + result.stderr)

    def test_packaged_app_builtin_provider_is_available_to_the_worker(self):
        resources = self.root / 'Packaged App.app/Contents/Resources'
        self.cjs = resources / 'glm/zcode.cjs'
        self.cjs.parent.mkdir(parents=True); self.cjs.touch()
        bundled = resources / 'config/provider/zcode-builtin.json'
        bundled.parent.mkdir(parents=True); bundled.write_text('{}')
        self.env.update(ZCODE_CJS=str(self.cjs), AUDIT_EXPECTED_PROVIDER=str(bundled.resolve()))
        self.env.pop('ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE', None)
        self.env.pop('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE', None)
        node = self.root / 'bin/node'
        node.write_text('#!/bin/bash\n[ "$ZCODE_BUILTIN_PROVIDER_CONFIG_FILE" = "$AUDIT_EXPECTED_PROVIDER" ] || { echo "missing builtin provider config" >&2; exit 1; }\ncat "$AUDIT_STDOUT"\nexit "$AUDIT_EXIT"\n')
        node.chmod(0o755)
        result = self.run_worker(self.response('TASK_RESULT: DONE'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, 'TASK_RESULT: DONE')

    def test_explicit_builtin_provider_path_takes_precedence(self):
        custom = self.root / 'custom provider.json'; custom.write_text('{}')
        bundled = self.root / 'provider/zcode-builtin.json'
        bundled.parent.mkdir(); bundled.write_text('{}')
        self.env['ZCODE_BUILTIN_PROVIDER_CONFIG_FILE'] = str(custom)
        self.env['ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE'] = str(bundled)
        node = self.root / 'bin/node'
        node.write_text('#!/bin/bash\n[ "$ZCODE_BUILTIN_PROVIDER_CONFIG_FILE" = "$AUDIT_EXPECTED_PROVIDER" ] || exit 1\ncat "$AUDIT_STDOUT"\nexit "$AUDIT_EXIT"\n')
        node.chmod(0o755)
        self.env['AUDIT_EXPECTED_PROVIDER'] = str(custom)
        result = self.run_worker(self.response('TASK_RESULT: DONE'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_bundled_override_seeds_the_bootstrap_input(self):
        custom = self.root / 'custom provider.json'; custom.write_text('{}')
        self.env.pop('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE', None)
        self.env['ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE'] = str(custom)
        self.env['AUDIT_EXPECTED_PROVIDER'] = str(custom)
        node = self.root / 'bin/node'
        node.write_text('#!/bin/bash\n[ "$ZCODE_BUILTIN_PROVIDER_CONFIG_FILE" = "$AUDIT_EXPECTED_PROVIDER" ] || exit 1\ncat "$AUDIT_STDOUT"\nexit "$AUDIT_EXIT"\n')
        node.chmod(0o755)
        result = self.run_worker(self.response('TASK_RESULT: DONE'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exec_probe_seeds_builtin_without_replacing_personal_or_endpoint(self):
        bundled = self.root / 'provider/zcode-builtin.json'
        bundled.parent.mkdir(); bundled.write_text('{}')
        self.env.pop('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE', None)
        self.env.pop('ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE', None)
        self.env.update(ZCODE_PERSONAL_PROVIDER_CONFIG_FILE='explicit personal.json',
                        ZCODE_ENDPOINT='https://example.invalid/custom')
        node = self.root / 'bin/node'
        node.write_text('#!/usr/bin/env python3\nimport json,os\nprint(json.dumps({k:v for k,v in os.environ.items() if k.startswith("ZCODE_")}))\n')
        node.chmod(0o755)
        result = subprocess.run(['python3', str(REPO / 'ck-zcode-session.py'),
                                 'exec', str(self.cjs), 'node', str(self.cjs), '--prompt', 'offline'],
                                cwd=self.root, env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(actual['ZCODE_BUILTIN_PROVIDER_CONFIG_FILE'], str(bundled.resolve()))
        self.assertEqual(actual['ZCODE_PERSONAL_PROVIDER_CONFIG_FILE'], 'explicit personal.json')
        self.assertEqual(actual['ZCODE_ENDPOINT'], 'https://example.invalid/custom')
        self.assertNotIn('ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE', actual)

    def test_auth_and_network_classes_remain_distinct(self):
        self.assert_error(self.run_worker("", "401 Unauthorized", 1), "auth")
        self.assert_error(self.run_worker("", "ECONNRESET", 1), "transient")


if __name__ == "__main__":
    unittest.main(verbosity=2)
