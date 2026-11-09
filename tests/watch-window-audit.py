#!/usr/bin/env python3
"""Offline watchdog window regressions; probes and launches are always fakes."""
import datetime as dt
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

# CK_AUDIT_SOURCE: 指向保存的旧源码目录 (需含 burn-watch.sh 与 ck-window.py),
# 用于回归重放 — 先在旧实现上跑红, 再在当前源码上跑绿 (watchdog-deploy-audit 同款)
REPO = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parent.parent))


def epoch(local):
    return int(dt.datetime.fromisoformat(local).replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())


class WatchWindowAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-watch-window-")
        self.root = Path(self.tmp.name)
        self.processes = []
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.lib = self.root / "lib"
        self.lib.mkdir()
        source = (REPO / "burn-watch.sh").read_text().split('\ncase "${1:-}" in\n')[0]
        self.source = self.lib / "burn-watch.sh"
        self.source.write_text(source)
        (self.lib / "ck-window.py").symlink_to(REPO / "ck-window.py")
        self.projects = self.root / "Documents/work/code/AI/AIworkspace"
        (self.root / ".codingkeeper").mkdir()
        (self.root / ".codex").mkdir()
        self.furnace = str(self.projects / "fingerprint")
        self.scaffold(self.project("fingerprint"))
        self.clock = self.root / "clock"
        self.clock.write_text(str(epoch("2026-11-05T23:00:00")))
        self.env = dict(os.environ, HOME=str(self.root), TMPDIR=str(self.root),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        CODEXC_ACTIVE_WINDOW="23:00-09:00", CODEXC_ACTIVE_TZ="Asia/Shanghai",
                        BURN_WATCH_NOTIFY="0", WATCH_ROOT=str(self.root), WATCH_SOURCE=str(self.source),
                        WATCH_CLOCK=str(self.clock), TZ="Pacific/Honolulu")
        self.script("python3", "#!" + sys.executable + "\n" +
                    "import os, sys\nfrom pathlib import Path\n" +
                    "args = sys.argv[1:]\n" +
                    "if args and Path(args[0]).name == 'ck-window.py':\n" +
                    "    mode = os.environ.get('WATCH_HELPER_MODE')\n" +
                    "    if mode == 'fail': sys.exit(2)\n" +
                    "    if mode == 'malformed': print('allowed'); sys.exit(0)\n" +
                    "    args += ['--now', Path(os.environ['WATCH_CLOCK']).read_text().strip()]\n" +
                    "os.execv(" + repr(sys.executable) + ", [" + repr(sys.executable) + "] + args)\n")
        self.script("probe", '#!/bin/bash\nprintf "probe\\n" >> "$WATCH_ROOT/probes"\n'
                    '[ "${WATCH_PROBE_FAIL:-0}" = 1 ] || printf \'{"response":"ok"}\\n\'\n')
        self.script("nohup", '#!/bin/bash\nprintf "%s|%s|%s\\n" "$CODEXC_ACTIVE_WINDOW" '
                    '"$CODEXC_ACTIVE_TZ" "$*" >> "$WATCH_ROOT/launches"\n')
        self.script("sqlite3", '#!/bin/bash\nprintf "%s\\n" "$@" > "$WATCH_ROOT/sqlite-args"\n'
                    'printf "0.0M\\n"\n')

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            process.communicate(timeout=5)
        self.tmp.cleanup()

    def project(self, name, parent=None):
        base = parent if parent is not None else self.projects
        kd = base / name / ".codingkeeper"
        kd.mkdir(parents=True)
        (kd / "journal").touch()
        return kd

    def scaffold(self, kd):
        """注册表驱动的炉子必须三件套齐全 (c9630a8), 否则巡逻跳过并告警。"""
        for name in ("queue.md", "gate.sh", "review-leaf.sh"):
            (kd / name).touch()
        registry = self.root / ".codingkeeper/projects"
        registry.parent.mkdir(parents=True, exist_ok=True)
        with open(registry, "a") as handle:
            handle.write(str(kd.parent) + "\n")
        return kd

    def script(self, name, source):
        path = self.bin / name
        path.write_text(source)
        path.chmod(0o755)
        return path

    def shell(self, body, fake_revive=False):
        setup = (f'. "$WATCH_SOURCE"\nZCJS="$WATCH_ROOT/bin/probe"\n'
                 f'CK_FURNACE="{self.furnace}"\nproj_alive() {{ return 1; }}\n')
        setup += 'sleep() { if [ -n "${WATCH_NEXT_TIME:-}" ]; then printf "%s" "$WATCH_NEXT_TIME" > "$WATCH_CLOCK"; fi; }\n'
        if fake_revive:
            setup += 'revive() { printf "%s\\n" "$1" >> "$WATCH_ROOT/revived"; }\n'
        result = subprocess.run(["/bin/bash", "-c", setup + body], cwd=self.root, env=self.env,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def reset_markers(self):
        for name in ("probes", "revived", "launches"):
            (self.root / name).unlink(missing_ok=True)

    def test_patrol_window_boundaries_use_shanghai_even_with_foreign_host_timezone(self):
        for local, allowed in (("2026-11-05T22:59:59", False), ("2026-11-05T23:00:00", True),
                               ("2026-11-06T08:59:59", True), ("2026-11-06T09:00:00", False),
                               ("2026-11-06T16:00:00", False)):
            with self.subTest(local=local):
                self.reset_markers()
                (self.root / ".codingkeeper/burn-ALERTS.txt").unlink(missing_ok=True)
                self.clock.write_text(str(epoch(local)))
                self.shell("patrol_once\n", fake_revive=True)
                self.assertEqual((self.root / "revived").exists(), allowed)

    def test_probe_window_boundaries(self):
        for local, allowed in (("2026-11-05T22:59:59", False), ("2026-11-05T23:00:00", True),
                               ("2026-11-06T08:59:59", True), ("2026-11-06T09:00:00", False)):
            with self.subTest(local=local):
                self.reset_markers()
                self.clock.write_text(str(epoch(local)))
                result = self.shell('cli_alive; printf "rc=%s" "$?"\n')
                self.assertEqual((self.root / "probes").exists(), allowed)
                self.assertEqual(result.stdout, "rc=0" if allowed else "rc=125")

    def test_probe_retry_rechecks_window_after_sleep(self):
        self.clock.write_text(str(epoch("2026-11-06T08:59:59")))
        self.env.update(WATCH_PROBE_FAIL="1", WATCH_NEXT_TIME=str(epoch("2026-11-06T09:00:00")))
        result = self.shell('cli_alive; printf "rc=%s" "$?"\n')
        self.assertEqual((self.root / "probes").read_text(), "probe\n")
        self.assertEqual(result.stdout, "rc=125")

    def test_direct_revive_is_guarded_and_forwards_the_policy(self):
        for local, allowed in (("2026-11-06T09:00:00", False), ("2026-11-05T23:00:00", True)):
            with self.subTest(local=local):
                self.reset_markers()
                self.clock.write_text(str(epoch(local)))
                result = self.shell('revive "$CK_FURNACE"; printf "rc=%s" "$?"\n')
                if allowed:
                    deadline = time.monotonic() + 2
                    while not (self.root / "launches").exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual((self.root / "launches").read_text(), "23:00-09:00|Asia/Shanghai|zcodec run\n")
                else:
                    self.assertEqual(result.stdout, "rc=125")
                    self.assertFalse((self.root / "launches").exists())

    def test_registry_project_outside_workspace_prefix_revives(self):
        # 注册表可登记任意路径 (c9630a8); revive 仍从 Documents 前缀重建目录时,
        # 前缀外炉子的 park 自愈会清掉 halt 却永远起不来 — 复燃必须吃完整路径
        outside = self.scaffold(self.project("outsider", parent=self.root / "elsewhere"))
        (outside / "loop.halt").write_text("review rounds exhausted (6)\n")
        (self.root / ".codingkeeper/projects").write_text(str(outside.parent) + "\n")
        self.clock.write_text(str(epoch("2026-11-05T23:00:00")))
        self.shell("patrol_once\n")
        self.assertTrue((self.root / "launches").exists(),
                        "前缀外注册炉子必须能被真实 revive 拉起 (nohup fake 落 launches)")

    def test_probe_cleanup_excludes_live_sessions_across_registry_paths(self):
        # 同类病灶: cleanup 的活链排除曾用 Documents 硬编码 glob — 注册表前缀外
        # 炉子的活会话进不了排除名单, 自动化标题的活链会被误删
        outside = self.scaffold(self.project("outsider", parent=self.root / "elsewhere"))
        (outside / "zcode-session-id").write_text("sess_outsidelive0000000000000000000\n")
        self.shell("cleanup_probe_sessions\n")
        sql = (self.root / "sqlite-args").read_text()
        self.assertIn("sess_outsidelive0000000000000000000", sql,
                      "前缀外炉子的活链 sid 必须进 NOT IN 排除名单")

    def test_watchdog_defaults_to_unrestricted_burn(self):
        self.env.pop("CODEXC_ACTIVE_WINDOW")
        self.env.pop("CODEXC_ACTIVE_TZ")
        self.clock.write_text(str(epoch("2026-11-06T16:00:00")))
        self.shell("patrol_once\n", fake_revive=True)
        self.assertTrue((self.root / "revived").exists())

    def test_explicit_empty_window_allows_patrol_and_probe(self):
        self.env['CODEXC_ACTIVE_WINDOW'] = ''
        self.clock.write_text(str(epoch('2026-11-06T16:00:00')))
        self.shell('patrol_once\ncli_alive\n', fake_revive=True)
        self.assertTrue((self.root / 'revived').exists())
        self.assertTrue((self.root / 'probes').exists())

    def test_revive_preserves_custom_timezone(self):
        self.env['CODEXC_ACTIVE_TZ'] = 'Asia/Singapore'
        self.shell('revive "$CK_FURNACE"\n')
        deadline = time.monotonic() + 2
        while not (self.root / 'launches').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIn('23:00-09:00|Asia/Singapore|', (self.root / 'launches').read_text())

    def test_invalid_policy_or_helper_failure_fails_closed(self):
        for config in ({"CODEXC_ACTIVE_WINDOW": "bad"}, {"CODEXC_ACTIVE_TZ": "invalid/timezone"},
                       {"WATCH_HELPER_MODE": "fail"}, {"WATCH_HELPER_MODE": "malformed"}):
            with self.subTest(config=config):
                previous = dict(self.env)
                self.env.update(config)
                self.reset_markers()
                self.shell('patrol_once\ncli_alive || :\nrevive "$CK_FURNACE" || :\n', fake_revive=False)
                self.assertFalse((self.root / "launches").exists())
                self.assertFalse((self.root / "probes").exists())
                self.env = previous

    def test_missing_helper_fails_closed(self):
        (self.lib / "ck-window.py").unlink()
        self.shell('patrol_once\ncli_alive || :\nrevive "$CK_FURNACE" || :\n')
        self.assertFalse((self.root / "launches").exists())
        self.assertFalse((self.root / "probes").exists())

    def test_quota_and_manual_halts_survive_allowed_window(self):
        halt = self.projects / "fingerprint/.codingkeeper/loop.halt"
        for reason in ("quota: current package not active\n", "manual pause\n"):
            with self.subTest(reason=reason):
                halt.write_text(reason)
                self.shell('patrol_once\nrevive "$CK_FURNACE" || :\n')
                self.assertEqual(halt.read_text(), reason)
                self.assertFalse((self.root / "launches").exists())

    def test_failed_revive_does_not_consume_daily_recovery_budget(self):
        self.shell("revive() { return 1; }\npatrol_once\n")
        alerts = self.root / ".codingkeeper/burn-ALERTS.txt"
        self.assertNotIn("复燃#", alerts.read_text() if alerts.exists() else "")

    def test_accounting_outside_window_opens_database_read_only(self):
        self.clock.write_text(str(epoch("2026-11-06T16:00:00")))
        self.shell("patrol_once\n", fake_revive=True)
        self.assertIn("今日token=0.0M", (self.root / ".codingkeeper/burn-log.txt").read_text())
        self.assertEqual((self.root / "sqlite-args").read_text().splitlines()[0], "-readonly")
        self.assertFalse((self.root / "revived").exists())

    def test_patrol_rechecks_between_projects(self):
        self.scaffold(self.project("sale"))
        self.clock.write_text(str(epoch("2026-11-06T08:59:59")))
        self.env["WATCH_NEXT_TIME"] = str(epoch("2026-11-06T09:00:00"))
        self.shell('revive() { printf "%s\\n" "$1" >> "$WATCH_ROOT/revived"; '
                   'printf "%s" "$WATCH_NEXT_TIME" > "$WATCH_CLOCK"; }\npatrol_once\n')
        self.assertEqual((self.root / "revived").read_text(), self.furnace + "\n")

    def test_symlink_entry_resolves_sibling_policy_helper(self):
        link = self.bin / "watchdog-link"
        link.symlink_to(self.source)
        self.env["WATCH_SOURCE"] = str(link)
        self.shell("patrol_once\n", fake_revive=True)
        self.assertTrue((self.root / "revived").exists())

    def real_entry(self, command="run"):
        # Exercise the executable entry and both exec transitions with the
        # same close_fds/start_new_session settings as production deployment.
        self.clock.write_text(str(epoch("2026-11-06T16:00:00")))
        self.script("sleep", "#!" + sys.executable + "\n" +
                    "import os, time\nfrom pathlib import Path\n" +
                    "try:\n    os.fstat(9)\n    state = 'inherited'\n" +
                    "except OSError:\n    state = 'closed'\n" +
                    "Path(os.environ['WATCH_ROOT'], 'child-lock-fd').write_text(state)\n" +
                    "time.sleep(300)\n")
        process = subprocess.Popen([str(REPO / "burn-watch.sh"), command], cwd=self.root,
                                   env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, close_fds=True, start_new_session=True)
        self.processes.append(process)
        return process

    def wait_for_patrol(self, process):
        account = self.root / ".codingkeeper/burn-log.txt"
        child_fd = self.root / "child-lock-fd"
        # Real exec transitions include multiple Python shim startups; a
        # measured cold start can take over 7 seconds on a loaded host.
        until = time.monotonic() + 15
        while time.monotonic() < until and process.poll() is None:
            if account.exists() and child_fd.exists():
                return
            time.sleep(0.02)
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=2)
            self.fail(f"watchdog entry exited {process.returncode}: {stdout}{stderr}")
        self.fail("watchdog entry never reached its first patrol and sleep")

    def test_real_entry_starts_excludes_overlap_and_recovers_after_termination(self):
        first = self.real_entry()
        self.wait_for_patrol(first)
        self.assertEqual((self.root / "child-lock-fd").read_text(), "closed")
        self.assertEqual((self.root / ".codingkeeper/watchdog.lock.flock").read_text().strip(), str(first.pid))
        second = self.real_entry()
        stdout, stderr = second.communicate(timeout=5)
        self.assertNotEqual(second.returncode, 0, stdout + stderr)
        self.assertIn("watchdog 已在运行", stderr)
        os.killpg(first.pid, signal.SIGTERM)
        first.communicate(timeout=5)
        (self.root / ".codingkeeper/burn-log.txt").unlink()
        (self.root / "child-lock-fd").unlink()
        third = self.real_entry()
        self.wait_for_patrol(third)
        self.assertFalse((self.root / "launches").exists())
        self.assertFalse((self.root / "probes").exists())

    def test_real_internal_entry_refuses_missing_lock_descriptor(self):
        process = self.real_entry("__locked-run")
        stdout, stderr = process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        self.assertIn("watchdog: missing lock", stderr)
        self.assertFalse((self.root / ".codingkeeper/burn-log.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
