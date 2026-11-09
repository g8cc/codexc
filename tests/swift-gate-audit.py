#!/usr/bin/env python3
"""Swift gate regressions: broken-toolchain honesty and preserved gate teeth.

2026-11-10: CLT 编译器 (6.3.3) 与 SDK swiftinterface (6.3.2) 错配后, swiftc 对
trivial 探针也会秒败或挂死。门禁必须把环境问题 (大声 SKIP) 与代码问题 (红) 分开,
探针全程超时封顶, 不许环境故障挂死 gate。所有 swiftc 都是本地假件, 不碰真工具链。
"""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / 'tests' / 'swift-gate.sh'

FAKE_SWIFTC = """#!/usr/bin/env python3
import os, sys, time
mode = os.environ.get('FAKE_SWIFT_MODE', 'ok')
args = sys.argv[1:]
if mode == 'hang':
    time.sleep(300)
if '-typecheck' not in args:
    sys.exit(3)
targets = [a for a in args if a.endswith('.swift')]
probe = any('swift-gate.' in a for a in targets)  # 探针文件名: swift-gate.XXXXXX[.probe.swift]
if mode == 'mismatch' and probe:
    print('error: this SDK is not supported by the compiler', file=sys.stderr)
    sys.exit(1)
if mode == 'teeth' and targets and not probe:
    for a in targets:
        if 'GATE_BROKEN_MARKER' in open(a).read():
            print('error: broken code', file=sys.stderr)
            sys.exit(1)
sys.exit(0)
"""


class SwiftGateAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-swift-gate-audit-')
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'swiftc'
        fake.write_text(FAKE_SWIFTC)
        fake.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        SWIFT_GATE_PROBE_TIMEOUT='5', FAKE_SWIFT_MODE='ok')
        self.panel = self.root / 'panel.swift'
        self.panel.write_text('import AppKit\nlet ok = 1\n')

    def tearDown(self):
        self.tmp.cleanup()

    def run_gate(self, *args):
        return subprocess.run([str(GATE), *args], capture_output=True, text=True,
                              env=self.env, timeout=60)

    def test_healthy_toolchain_typechecks_target(self):
        result = self.run_gate(str(self.panel))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('SKIP', result.stdout)

    def test_probe_only_reports_health(self):
        self.assertEqual(self.run_gate('--probe-only').returncode, 0)
        self.env['FAKE_SWIFT_MODE'] = 'mismatch'
        result = self.run_gate('--probe-only')
        self.assertEqual(result.returncode, 2)
        self.assertIn('SKIP', result.stdout)

    def test_broken_toolchain_skips_loudly_without_failing_gate(self):
        for mode in ('mismatch', 'hang'):
            with self.subTest(mode=mode):
                self.env['FAKE_SWIFT_MODE'] = mode
                started = time.monotonic()
                result = self.run_gate(str(self.panel))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SKIP', result.stdout)
                self.assertIn('工具链损坏', result.stdout)
                self.assertIn('修复', result.stdout)
                self.assertLess(time.monotonic() - started, 30,
                                '探针必须被看门狗封顶 — 环境故障不许挂死门禁')

    def test_healthy_probe_still_fails_broken_code(self):
        self.env['FAKE_SWIFT_MODE'] = 'teeth'
        self.panel.write_text('import AppKit\nlet broken = "GATE_BROKEN_MARKER"\n')
        result = self.run_gate(str(self.panel))
        self.assertNotEqual(result.returncode, 0, '门禁的牙: 探针健康时, 代码坏必须仍然红')

    def test_run_all_and_desktop_audit_route_through_the_gate(self):
        run_all = (ROOT / 'tests' / 'run-all').read_text()
        self.assertIn('tests/swift-gate.sh desktop/CodingKeeperBar.swift', run_all)
        self.assertIn('tests/swift-gate.sh', run_all.split('for f in ')[1].split(';')[0],
                      'swift-gate.sh 自身必须进 bash -n 门禁')
        desktop = (ROOT / 'tests' / 'desktop-audit.py').read_text()
        self.assertIn('--probe-only', desktop, 'desktop-audit 必须先做工具链自检')


if __name__ == '__main__':
    unittest.main()
