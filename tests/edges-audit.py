#!/usr/bin/env python3
"""Offline adapter/watchdog/desktop regression tests. Never contacts a model."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parent.parent


class EdgesAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-edges-")
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])

    def tearDown(self):
        self.tmp.cleanup()

    def script(self, name, source):
        path = self.bin / name
        path.write_text(source)
        path.chmod(0o755)
        return path

    def run_shell(self, source, **kw):
        return subprocess.run(["/bin/bash", "-c", source], cwd=self.root, env=self.env,
                              text=True, capture_output=True, timeout=20, **kw)

    def zcode(self, raw, sid=None):
        data = self.root / "output"
        data.write_text(raw)
        self.script("node", '#!/bin/bash\ncat "$AUDIT_OUTPUT"\n')
        cjs = self.root / "fake.cjs"
        cjs.touch()
        session = self.root / "session"
        if sid is not None:
            session.write_text(sid)
        env = dict(self.env, ZCODE_CJS=str(cjs), ZCODE_SESSION_FILE=str(session),
                   AUDIT_OUTPUT=str(data), TMPDIR=str(self.root))
        result = subprocess.run([str(REPO / "codexc-zcode-worker")], input="task", text=True,
                                cwd=self.root, env=env, capture_output=True, timeout=20)
        return result, session

    def test_large_zcode_response(self):
        response = "x" * (2 * 1024 * 1024) + "\nTASK_RESULT: DONE"
        result, _ = self.zcode(json.dumps({"sessionId": "sess_large", "response": response}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, response)

    def test_ndjson_session_and_response_in_separate_events(self):
        result, session = self.zcode('\n'.join([json.dumps({"sessionId": "sess_separate"}),
                                               json.dumps({"response": "TASK_RESULT: DONE"})]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(session.exists(), "session continuity was lost")
        self.assertEqual(session.read_text(), "sess_separate\n")
        self.assertEqual(session.stat().st_mode & 0o777, 0o600)

    def test_empty_final_response_does_not_reuse_earlier_done(self):
        result, _ = self.zcode('{"response":"TASK_RESULT: DONE"}\n{"response":""}\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("TASK_RESULT: DONE", result.stdout)

    def test_invalid_session_does_not_truncate_existing(self):
        result, session = self.zcode(json.dumps({"sessionId": ["bad"], "response": "TASK_RESULT: DONE"}),
                                    "sess_previous\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(session.read_text(), "sess_previous\n")

    def test_worker_entry_paths_are_shell_quoted(self):
        folder = self.root / "repo with spaces"
        folder.mkdir()
        for name in ("zcodec", "dshc"):
            shutil.copy2(REPO / name, folder / name)
        (folder / "codexc-headless").write_text('#!/bin/bash\neval "$CODEXC_HEADLESS_CMD"\n')
        (folder / "codexc-headless").chmod(0o755)
        for tool in ("zcode", "dsh"):
            worker = folder / ("codexc-" + tool + "-worker")
            worker.write_text('#!/bin/bash\nprintf "worker-ok"\n')
            worker.chmod(0o755)
            result = subprocess.run([str(folder / ("zcodec" if tool == "zcode" else "dshc")), "run"],
                                    env=self.env, text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "worker-ok")

    def test_explicit_ck_codex_overrides_inherited_tool(self):
        folder = self.root / "entry"
        folder.mkdir()
        shutil.copy2(REPO / "ck", folder / "ck")
        worker = folder / "codexc"
        worker.write_text('#!/bin/bash\nprintf "%s" "$CODEXC_TOOL"\n')
        worker.chmod(0o755)
        result = subprocess.run([str(folder / "ck"), "codex"], env=dict(self.env, CODEXC_TOOL="claude"),
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "codex")

    def test_dsh_cli_arguments_pass_through_without_evaluation(self):
        dsh = self.script("dsh-fake", '#!/bin/bash\nprintf "%s\\n" "$@"\n')
        result = subprocess.run([str(REPO / "dshc"), "--profile", "some profile", "--version"],
                                env=dict(self.env, DSH_BIN=str(dsh)), text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "--profile\nsome profile\n--version\n")

    def watchdog_lib(self):
        source = (REPO / "burn-watch.sh").read_text().split('\ncase "${1:-}" in\n')[0]
        # 注册表驱动炉队 (c9630a8): fixture 经假 HOME 的注册表注入, 绝不触碰真实
        # 家目录。旧的硬编码前缀 replace 在 revive/cleanup 改吃完整路径后已无目标,
        # 留着只会让巡逻发现零炉、预算与 halt 分支空转。
        self.env["HOME"] = str(self.root)
        (self.root / ".codingkeeper").mkdir(exist_ok=True)
        fingerprint = self.root / "fingerprint" / ".codingkeeper"
        fingerprint.mkdir(parents=True, exist_ok=True)
        for name in ("queue.md", "gate.sh", "review-leaf.sh"):
            (fingerprint / name).touch()
        (self.root / ".codingkeeper/projects").write_text(str(self.root / "fingerprint") + "\n")
        source += '\nLOG="$AUDIT_ROOT/watch.log"; ALERT="$AUDIT_ROOT/alerts.txt"; ACCOUNT="$AUDIT_ROOT/account.txt"\n'
        # bash -c 管道里 BASH_SOURCE 为空, WATCH_DIR 回退链断在假 HOME — 直接指仓库真源
        source += f'WATCH_DIR="{REPO}"\n'
        source += 'proj_alive() { return 1; }; revive() { printf "revived\\n" >> "$AUDIT_ROOT/revived"; }; sqlite3() { :; }\n'
        self.env["AUDIT_ROOT"] = str(self.root)
        self.env["BURN_WATCH_NOTIFY"] = "0"
        return source

    def test_watchdog_daily_revive_limit(self):
        (self.root / "fingerprint" / ".codingkeeper").mkdir(parents=True)
        date = subprocess.check_output(["date", "+%F"], text=True).strip()
        (self.root / "alerts.txt").write_text((date + " 00:00:00 | fingerprint | 复燃#fingerprint#0\n") * 2)
        result = self.run_shell(self.watchdog_lib() + '\npatrol_once\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("复燃超限(2)", (self.root / "alerts.txt").read_text(),
                      "预算路径必须真跑到 — 空转巡逻 (零炉) 不能算通过")
        self.assertFalse((self.root / "revived").exists(), "daily cap failed to stop third revival")

    def test_watchdog_preserves_project_halt(self):
        kd = self.root / "fingerprint" / ".codingkeeper"
        kd.mkdir(parents=True)
        (kd / "loop.halt").touch()
        (self.root / "watch.log").write_text("2026-01-01 headless: parked: repeated empty turns\n")
        result = self.run_shell(self.watchdog_lib() + '\npatrol_once\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("项目已暂停", (self.root / "alerts.txt").read_text(),
                      "halt 分支必须真跑到 — 空转巡逻 (零炉) 不能算通过")
        self.assertFalse((self.root / "revived").exists(), "an unrelated global log overrode this project's halt")

    def test_watchdog_lock_excludes_overlap_and_recovers_after_death(self):
        lockdir = self.root / "watchdog.lock"
        lockdir.mkdir()
        (lockdir / "pid").write_text("999999999\n")
        worker = self.script("lock-worker", '#!/bin/bash\nprintf "acquired\\n"\nsleep "${AUDIT_LOCK_SLEEP:-2}" 9>&-\nexit 0\n')
        lib = self.watchdog_lib()
        self.env.update(AUDIT_LOCKDIR=str(lockdir), AUDIT_LOCK_WORKER=str(worker))
        command = lib + '\nLOCKDIR="$AUDIT_LOCKDIR"; watchdog_lock_exec "$AUDIT_LOCK_WORKER"\n'
        first = subprocess.Popen(["/bin/bash", "-c", command], cwd=self.root, env=self.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(first.stdout.readline().strip(), "acquired")
            second = self.run_shell(command)
            self.assertNotEqual(second.returncode, 0, "two watchdogs acquired the same lock")
            first.kill()
            first.wait(timeout=5)
            self.env["AUDIT_LOCK_SLEEP"] = "0"
            third = self.run_shell(command)
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertIn("acquired", third.stdout)
        finally:
            if first.poll() is None:
                first.kill()
            first.communicate(timeout=5)

    def test_watchdog_refuses_symlink_lock(self):
        victim = self.root / "victim"
        victim.write_text("keep")
        lockdir = self.root / "watchdog.lock"
        Path(str(lockdir) + ".flock").symlink_to(victim)
        self.env["AUDIT_LOCKDIR"] = str(lockdir)
        result = self.run_shell(self.watchdog_lib() + '\nLOCKDIR="$AUDIT_LOCKDIR"; watchdog_lock_exec /bin/true\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(victim.read_text(), "keep")

    def test_install_replaces_directory_symlink_without_writing_inside(self):
        target = self.root / "target"
        target.mkdir()
        source = self.root / "source"
        source.touch()
        dest = self.root / "dest"
        dest.symlink_to(target, target_is_directory=True)
        lib = (REPO / "install.sh").read_text().split('\necho "==== scripts ===="')[0]
        self.env.update(AUDIT_SOURCE=str(source), AUDIT_DEST=str(dest))
        result = self.run_shell(lib + '\nlink "$AUDIT_SOURCE" "$AUDIT_DEST"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dest.resolve(), source.resolve())
        self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
