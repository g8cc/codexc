#!/usr/bin/env python3
"""两通道 cmd_init 门禁生成对齐回归: codexc-loop 与 codexc-headless 曾漂移。

漂移实证 (2026-11-10 可维护性轮): loop 的 init 探测测试命令生成真门禁,
headless 永远写占位门禁 — 而 headless 启动路径的 require_gate_check 对占位
当场停炉, 无人值守通道自动初始化后永远无法自举。集中化到 ck-common.sh
(gate_init_write) 后, 两通道对同一项目必须产出同类的门禁。
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENTRIES = ('codexc-loop', 'codexc-headless')


class InitParityAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-init-parity-')
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, CK_TEST_FAKE_HOME='1')

    def tearDown(self):
        self.tmp.cleanup()

    def init(self, entry, project):
        (self.root / project).mkdir(parents=True, exist_ok=True)
        return subprocess.run([str(REPO / entry), 'init'], cwd=str(self.root / project),
                              env=self.env, text=True, capture_output=True, timeout=60)

    def gate(self, project):
        return (self.root / project / '.codingkeeper' / 'gate.sh').read_text()

    def test_detectable_project_yields_real_gate_on_both_channels(self):
        # 漂移实证场景: 带 Makefile test 目标的项目 — headless 旧实现只写占位,
        # 启动即被 require_gate_check 停炉 (无人值守通道无法自举)
        for entry in ENTRIES:
            with self.subTest(entry=entry):
                (self.root / entry).mkdir(parents=True, exist_ok=True)
                (self.root / entry / 'Makefile').write_text('test:\n\techo ok\n')
                result = self.init(entry, entry)
                self.assertEqual(result.returncode, 0, result.stderr)
                gate = self.gate(entry)
                self.assertNotIn('CK_GATE_PLACEHOLDER', gate, f'{entry} 必须探测生成真门禁')
                self.assertIn('make test', gate, f'{entry} 必须写入探测到的命令')

    def test_undetectable_project_yields_placeholder_on_both_channels(self):
        for entry in ENTRIES:
            with self.subTest(entry=entry):
                result = self.init(entry, f'bare-{entry}')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('CK_GATE_PLACEHOLDER', self.gate(f'bare-{entry}'))

    def test_both_channels_share_one_gate_generator(self):
        # 防回漂: 门禁生成语义只许住在 ck-common.sh, 通道内不得再有第二实现
        for entry in ENTRIES:
            src = (REPO / entry).read_text()
            self.assertNotIn('detect_test_cmds() {', src,
                             f'{entry} 不得自带测试命令探测实现')
            self.assertIn('gate_init_write', src, f'{entry} 必须调用共享生成器')
        self.assertIn('gate_init_write() {', (REPO / 'ck-common.sh').read_text())


if __name__ == '__main__':
    unittest.main()
