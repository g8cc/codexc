#!/usr/bin/env python3
"""Watchdog deploy regressions: midnight re-exec lock survival + launchd runtime copy.

2026-11-10 双故障回归锁:
1. 翻日 exec 曾放在 patrol_once 内, 而巡逻以 9>&- 运行 — exec 出的新实例
   fstat(9) 报 EBADF, "missing lock" 自杀, 看门狗零点必死。
2. plist 曾直指 ~/Documents 下的脚本, launchd 拉起的 bash 被 TCC 内核拒绝
   (System Policy deny file-read-data), KeepAlive 三连拒后任务被移除,
   看门狗静默死亡 15 小时。探针证实 launchd 进程对 ~/Documents 一律 DENIED。
"""
import os
import plistlib
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parents[1]))
HOME = Path.home()


class WatchdogDeployAudit(unittest.TestCase):
    def setUp(self):
        self.world = Path(os.environ.get('CK_TEST_TMP', '/private/tmp')) / 'ck-watchdog-deploy-selftest'
        self.home = self.world / 'home'
        (self.home / '.codingkeeper').mkdir(parents=True, exist_ok=True)
        self.flock = self.home / '.codingkeeper' / 'watchdog.lock.flock'
        self.flock.touch()
        self.processes = []

    def tearDown(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if self.world.exists():
            subprocess.run(['rm', '-rf', str(self.world)], check=False)

    def plist_args(self, path):
        with open(path, 'rb') as fh:
            return plistlib.load(fh)['ProgramArguments']

    # ---- 静态断言 (可移植) ----

    def test_packaging_plist_script_outside_documents(self):
        args = self.plist_args(ROOT / 'packaging' / 'com.codingkeeper.watchdog.plist')
        self.assertEqual(args[0], '/bin/bash', args)
        self.assertNotIn('/Documents/', args[1],
                         'launchd 拉起的进程读不了 ~/Documents (TCC) — 运行位必须在 Documents 外')
        self.assertTrue(args[1].endswith('/.codingkeeper/bin/burn-watch.sh'),
                        '运行位应指向 ~/.codingkeeper/bin/ 副本')
        self.assertEqual(args[2], 'run')

    def test_daily_plist_script_outside_documents(self):
        # com.codexc.daily 同病: 2026-11-02 起从未跑成过 (日志五条 Operation not permitted)
        args = self.plist_args(ROOT / 'packaging' / 'com.codexc.daily.plist')
        self.assertNotIn('/Documents/', args[0],
                         'daily 脚本运行位必须在 Documents 外 (TCC)')
        self.assertTrue(args[0].endswith('/.codingkeeper/bin/codexc-daily'), args)

    def test_install_script_covers_deploy_steps(self):
        script = (ROOT / 'packaging' / 'install-watchdog.sh').read_text()
        for needle in ('cp "$repo/burn-watch.sh"', 'cp "$repo/codexc-daily"',
                       'cp "$repo/ck-watchdog-alive.sh"', 'bootout', 'bootstrap'):
            self.assertIn(needle, script)

    def test_watchdog_alive_checker_is_fda_free(self):
        """守夜员必须只碰 Documents 之外的东西, 否则 launchd 无 FDA 时它也瞎。"""
        src = (ROOT / 'ck-watchdog-alive.sh').read_text()
        self.assertNotIn('/Documents/', src, '守夜员不得依赖 Documents (TCC)')
        self.assertIn('watchdog.heartbeat', src)
        self.assertIn('-lt 900', src, '心跳 15 分钟陈旧阈值')
        self.assertIn('-lt 3600', src, '告警每小时去重')
        args = self.plist_args(ROOT / 'packaging' / 'com.codingkeeper.watchdog-alive.plist')
        self.assertNotIn('/Documents/', args[1])
        self.assertTrue(args[1].endswith('/.codingkeeper/bin/ck-watchdog-alive.sh'))

    def test_burn_watch_refreshes_runtime_copy(self):
        src = (ROOT / 'burn-watch.sh').read_text()
        self.assertIn('$HOME/.codingkeeper/bin/burn-watch.sh', src)
        self.assertIn('cmp -s', src, '运行位自愈刷新缺失')

    def test_watch_dir_falls_back_to_repo_from_bin_copy(self):
        # 副本目录没有 ck-window.py: WATCH_DIR 必须回退仓库真源, 否则
        # watch_window_open 对一切炉子 125, 巡逻全盲 (2026-11-10 首次从
        # bin 副本启动时发现, soul2soul/wechatflow 停转未被复燃)
        src = (ROOT / 'burn-watch.sh').read_text()
        self.assertIn('$WATCH_DIR/ck-window.py', src)
        self.assertIn('bw_repo_dir', src)

    def test_ck_init_furnace_scaffolds_and_registers(self):
        """生成器: 三件套 + 注册登记, 幂等 (重跑不炸不重复登记)。"""
        with tempfile.TemporaryDirectory(prefix='ck-init-furnace-', dir='/private/tmp') as tmp:
            home = Path(tmp) / 'home'
            (home / '.codingkeeper').mkdir(parents=True)
            proj = Path(tmp) / 'projA'
            proj.mkdir()
            env = {**os.environ, 'HOME': str(home)}
            run = subprocess.run(['bash', str(ROOT / 'ck-init-furnace'), str(proj)],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            ck = proj / '.codingkeeper'
            for f in ('queue.md', 'gate.sh', 'review-leaf.sh'):
                self.assertTrue((ck / f).exists(), f'missing {f}')
            self.assertIn('- [ ] 通读本仓库', (ck / 'queue.md').read_text())
            self.assertIn('渐进式', (ck / 'gate.sh').read_text())
            self.assertIn('codexc-review-leaf', (ck / 'review-leaf.sh').read_text())
            reg = home / '.codingkeeper' / 'projects'
            self.assertEqual(reg.read_text().strip().splitlines(), [str(proj)])
            run2 = subprocess.run(['bash', str(ROOT / 'ck-init-furnace'), str(proj), 'true'],
                                  env=env, capture_output=True, text=True)
            self.assertEqual(run2.returncode, 0, run2.stderr)
            self.assertEqual(reg.read_text().strip().splitlines(), [str(proj)],
                             '重复登记 = 炉队重复巡逻')
            # 幂等语义: 已存在的 gate 不被指定命令覆盖
            self.assertIn('渐进式', (ck / 'gate.sh').read_text())
            proj_b = Path(tmp) / 'projB'
            proj_b.mkdir()
            run3 = subprocess.run(['bash', str(ROOT / 'ck-init-furnace'), str(proj_b), 'true'],
                                  env=env, capture_output=True, text=True)
            self.assertEqual(run3.returncode, 0, run3.stderr)
            self.assertIn('true', (proj_b / '.codingkeeper' / 'gate.sh').read_text(),
                          '全新项目走指定命令路径')

    def test_midnight_exec_lives_outside_patrol(self):
        lines = (ROOT / 'burn-watch.sh').read_text().splitlines()
        exec_lines = [i for i, l in enumerate(lines) if 'exec /bin/bash "$0" __locked-run' in l]
        self.assertEqual(len(exec_lines), 1, f'翻日 exec 应恰好一处: {exec_lines}')
        loop_lines = [i for i, l in enumerate(lines) if l.strip() == 'while :; do']
        self.assertTrue(loop_lines, '主循环缺失')
        self.assertGreater(exec_lines[0], loop_lines[0],
                           '翻日 exec 必须在主循环 (fd 9 开启) 内, patrol_once 里 fd 9 已关 — 会 missing lock 自杀')

    # ---- 机器态断言 (部署过的机器上不得漂移) ----

    def test_runtime_copy_matches_repo_if_present(self):
        runtime = HOME / '.codingkeeper' / 'bin' / 'burn-watch.sh'
        if not runtime.exists():
            self.skipTest('运行位尚未部署 (packaging/install-watchdog.sh)')
        self.assertEqual(runtime.read_bytes(), (ROOT / 'burn-watch.sh').read_bytes(),
                         '运行副本与仓库漂移 — 重跑 packaging/install-watchdog.sh')

    def test_installed_plist_matches_packaging_if_present(self):
        for source, installed_path in (
                (ROOT / 'packaging' / 'com.codingkeeper.watchdog.plist',
                 HOME / 'Library' / 'LaunchAgents' / 'com.codingkeeper.watchdog.plist'),
                (ROOT / 'packaging' / 'com.codexc.daily.plist',
                 HOME / 'Library' / 'LaunchAgents' / 'com.codexc.daily.plist')):
            if not installed_path.exists():
                self.skipTest(f'{installed_path.name} 未安装')
            self.assertEqual(installed_path.read_bytes(), source.read_bytes(),
                             f'{installed_path.name} 与 packaging 源漂移 — 重跑 packaging/install-watchdog.sh')

    # ---- 进程级回归: __locked-run 在 fd 9 开启 (未持锁) 时必须存活 ----

    def test_locked_run_survives_with_open_fd9(self):
        env = dict(os.environ, HOME=str(self.home))
        script = ROOT / 'burn-watch.sh'
        errfile = self.home / 'watchdog-stderr.log'
        # stderr 走文件而非 PIPE: 活实例与其子进程握着管道写端, stderr.read()
        # 永远等不到 EOF (且 assert 的 msg 参数是无条件求值), 套件会挂死
        with open(errfile, 'wb') as ef:
            proc = subprocess.Popen(
                ['/bin/bash', '-c',
                 f'exec 9<"{self.flock}"; exec /bin/bash "{script}" __locked-run'],
                env=env, stdout=subprocess.DEVNULL, stderr=ef)
        self.processes.append(proc)
        time.sleep(4)
        self.assertIsNone(proc.poll(),
                          '__locked-run 退出: ' + errfile.read_text(errors='replace'))
        heartbeat = self.home / '.codingkeeper' / 'watchdog.heartbeat'
        self.assertTrue(heartbeat.exists(), '存活实例应写心跳')


if __name__ == '__main__':
    unittest.main()
