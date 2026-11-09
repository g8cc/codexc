#!/usr/bin/env python3
"""install.sh 依赖检查回归: 版本/能力感知, 不得只查存在性。

依赖声明 (README): python3 3.11+ (tomllib) / tmux 3.5+ (extended-keys CSI-u);
zcodec 通道另需 node >= 24。太旧的依赖必须在安装时拦下 — 存在但过旧会让
tomllib ImportError 或 CSI-u 失灵在运行深处才炸。所有解释器都是本地假件。
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# shebang 必须是真解释器绝对路径: env python3 会在 PATH 里命中假件自身 → 自递归
FAKE_PYTHON3 = """#!{real}
import os, sys
args = sys.argv[1:]
if args and args[0] == '-c' and 'tomllib' in args[1]:
    sys.exit(0 if os.environ.get('FAKE_PY_TOMLLIB', '1') == '1' else 1)
if '--version' in args:
    print(os.environ.get('FAKE_PY_VERSION', 'Python 3.9.6'))
    sys.exit(0)
os.execv({real!r}, [sys.executable] + args)
""".format(real=os.path.realpath(sys.executable))

FAKE_TMUX = '#!/bin/bash\necho "tmux ${FAKE_TMUX_VERSION:-3.5a}"\n'
FAKE_NODE = '#!/bin/bash\necho "${FAKE_NODE_VERSION:-v24.1.0}"\n'


class InstallDepsAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-install-deps-')
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.script('python3', FAKE_PYTHON3)
        self.script('tmux', FAKE_TMUX)
        self.script('node', FAKE_NODE)
        self.script('sqlite3', '#!/bin/bash\nexit 0\n')
        self.script('codex', '#!/bin/bash\nexit 0\n')
        self.script('swiftc', '#!/bin/bash\nexit 0\n')  # 本机真 swiftc 工具链损坏会挂死
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'])

    def tearDown(self):
        self.tmp.cleanup()

    def script(self, name, source):
        path = self.bin / name
        path.write_text(source)
        path.chmod(0o755)
        return path

    def run_install(self):
        return subprocess.run([str(REPO / 'install.sh')], env=self.env,
                              text=True, capture_output=True, timeout=60)

    def test_healthy_versions_pass_quietly(self):
        self.env.update(FAKE_PY_TOMLLIB='1', FAKE_TMUX_VERSION='3.5a', FAKE_NODE_VERSION='v24.1.0')
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('TOO OLD', result.stdout)
        self.assertIn('ok: python3', result.stdout)
        self.assertIn('ok: tmux', result.stdout)

    def test_python_without_tomllib_is_rejected(self):
        # 3.9 时代 macOS CLT 自带 python3 — 只查存在性会放行, 运行深处 tomllib 才炸
        self.env.update(FAKE_PY_TOMLLIB='0', FAKE_PY_VERSION='Python 3.9.6')
        result = self.run_install()
        self.assertIn('TOO OLD: python3 (3.9.6)', result.stdout)
        self.assertIn('需要 3.11+ (tomllib)', result.stdout)
        self.assertIn('Install the above before using codexc', result.stdout,
                      '过旧依赖计入 missing — 必须触发安装提示块')

    def test_tmux_below_3_5_is_rejected(self):
        self.env['FAKE_TMUX_VERSION'] = '3.3a'
        result = self.run_install()
        self.assertIn('TOO OLD: tmux (tmux 3.3a)', result.stdout)
        self.assertIn('需要 3.5+ (extended-keys CSI-u)', result.stdout)

    def test_node_old_and_healthy_lanes(self):
        # "node 未装" 分支在装有真 node 的机器上无法经 PATH 构造 (假件删除后
        # 真件仍在 PATH 尾部) — 缺席分支仅 2 行, 靠代码审查
        self.env['FAKE_NODE_VERSION'] = 'v18.0.0'
        result = self.run_install()
        self.assertIn('TOO OLD: node (v18.0.0)', result.stdout)
        self.assertIn('需要 >= 24', result.stdout)
        self.env['FAKE_NODE_VERSION'] = 'v24.1.0'
        result = self.run_install()
        self.assertNotIn('TOO OLD: node', result.stdout)


if __name__ == '__main__':
    unittest.main()
