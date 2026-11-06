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
                        AUDIT_STDOUT=str(self.out), AUDIT_STDERR=str(self.err), TMPDIR=str(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def run_worker(self, stdout, stderr="", rc=0):
        self.out.write_text(stdout)
        self.err.write_text(stderr)
        return subprocess.run([str(REPO / "codexc-zcode-worker")], input="offline test task", text=True,
                              cwd=self.root, env=dict(self.env, AUDIT_EXIT=str(rc)), capture_output=True, timeout=10)

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

    def test_auth_and_network_classes_remain_distinct(self):
        self.assert_error(self.run_worker("", "401 Unauthorized", 1), "auth")
        self.assert_error(self.run_worker("", "ECONNRESET", 1), "transient")


if __name__ == "__main__":
    unittest.main(verbosity=2)
