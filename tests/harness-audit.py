#!/usr/bin/env python3
"""Offline cancellation regressions for tests/isolate.py.

Every process and tmux executable used here is a local fixture. These tests
never invoke the user's tmux binary or server.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HarnessCancellationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-harness-audit-")
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "fake-repo"
        (self.repo / "tests").mkdir(parents=True)
        (self.root / "bin").mkdir()
        shutil.copy2(ROOT / "tests/isolate.py", self.repo / "tests/isolate.py")
        (self.repo / "tmux.conf").touch()
        (self.repo / "sync-prefix2.sh").write_text("#!/bin/bash\nexit 0\n")
        self.tmux_log = self.root / "fake-tmux.jsonl"
        fake_tmux = self.root / "bin/tmux"
        fake_tmux.write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "with open(os.environ['HARNESS_AUDIT_TMUX_LOG'], 'a') as out:\n"
            "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        )
        fake_tmux.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / "bin") + ":" + os.environ["PATH"],
                        HARNESS_AUDIT_TMUX_LOG=str(self.tmux_log))
        self.launcher = None
        self.process_group = None
        self.artifacts = None
        self.output_path = self.root / "launcher.log"
        self.output = self.output_path.open("wb")

    def tearDown(self):
        # Clean even when deliberately run against the old, leaking isolator.
        if self.launcher is not None and self.launcher.poll() is None:
            self.launcher.kill()
            self.launcher.wait(timeout=5)
        if self.process_group is not None:
            try:
                os.killpg(self.process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.output.close()
        if self.artifacts is not None:
            shutil.rmtree(self.artifacts, ignore_errors=True)
        self.tmp.cleanup()

    def wait_for(self, predicate, message, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.05)
        self.fail(message + "\n" + self.output_path.read_text(errors="replace"))

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def start(self, ignore_term_grandchild):
        if ignore_term_grandchild:
            body = (
                "import os,pathlib,signal,time; "
                "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                "pathlib.Path(os.environ['CK_TEST_ARTIFACTS']+'/grandchild.pid')"
                ".write_text(str(os.getpid())); time.sleep(60)"
            )
            script = ("#!/bin/bash\n" + shlex.quote(sys.executable) + " -c " + shlex.quote(body) + " &\n"
                      "echo $$ > \"$CK_TEST_ARTIFACTS/runner.pid\"\nwait\n")
        else:
            body = (
                "import os,pathlib,time; "
                "pathlib.Path(os.environ['CK_TEST_ARTIFACTS']+'/runner.pid')"
                ".write_text(str(os.getpid())); time.sleep(60)"
            )
            script = "#!/bin/bash\nexec " + shlex.quote(sys.executable) + " -c " + shlex.quote(body) + "\n"
        runner = self.repo / "tests/run-all"
        runner.write_text(script)
        runner.chmod(0o755)
        self.launcher = subprocess.Popen(
            [sys.executable, str(self.repo / "tests/isolate.py")], env=self.env,
            stdin=subprocess.DEVNULL, stdout=self.output, stderr=subprocess.STDOUT,
        )

        def artifact_path():
            for line in self.output_path.read_text(errors="replace").splitlines():
                if line.startswith("Test artifacts: "):
                    return Path(line.split(": ", 1)[1])
            return None

        self.artifacts = self.wait_for(artifact_path, "isolator did not publish artifacts")
        pid_file = self.artifacts / "runner.pid"
        self.wait_for(lambda: pid_file.exists() and pid_file.read_text().strip(), "fake runner did not start")
        self.process_group = int(pid_file.read_text())
        if ignore_term_grandchild:
            grandchild_file = self.artifacts / "grandchild.pid"
            self.wait_for(lambda: grandchild_file.exists() and grandchild_file.read_text().strip(),
                          "fake grandchild did not install its signal handler")
            return int(grandchild_file.read_text())
        return self.process_group

    def cancel_and_check(self, extra_pid):
        self.launcher.terminate()
        code = self.launcher.wait(timeout=12)
        self.assertEqual(code, 130, self.output_path.read_text(errors="replace"))
        self.wait_for(lambda: not self.alive(self.process_group), "runner survived cancellation", timeout=3)
        self.wait_for(lambda: not self.alive(extra_pid), "grandchild survived cancellation", timeout=3)
        self.assertTrue(self.tmux_log.exists(), "tmux cleanup was skipped")
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        self.assertEqual(calls, [["-S", str(self.artifacts / "tmux.sock"), "kill-server"]])

    def test_sigterm_cleans_runner_and_private_tmux(self):
        self.cancel_and_check(self.start(ignore_term_grandchild=False))

    def test_sigterm_kills_term_ignoring_grandchild_after_leader_exits(self):
        self.cancel_and_check(self.start(ignore_term_grandchild=True))


class FixtureProcessIsolationTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("fixture_processes", ROOT / "tests/fixture_processes.py")
        self.checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.checker)
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-fixture-process-audit-")
        self.root = Path(self.tmp.name)
        self.children = []

    def tearDown(self):
        for child in self.children:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait(timeout=5)
        self.tmp.cleanup()

    def fixture(self, name):
        directory = self.root / name
        directory.mkdir()
        script, pids = directory / "review.sh", directory / "pids"
        script.write_text('#!/bin/bash\n' +
                          'sleep 60 &\nchild=$!\nprintf "%s\\n%s\\n" "$$" "$child" > "$1"\nwait "$child"\n')
        child = subprocess.Popen(['/bin/bash', str(script), str(pids)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        self.children.append(child)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if pids.exists() and len(pids.read_text().splitlines()) == 2:
                return child, pids
            time.sleep(.02)
        self.fail('fixture did not record both PIDs')

    def test_other_live_reviewer_cannot_make_own_terminated_tree_fail(self):
        own, own_pids = self.fixture('own')
        other, _ = self.fixture('other')
        os.killpg(own.pid, signal.SIGKILL)
        own.wait(timeout=3)
        old_check = subprocess.run(['pgrep', '-f', 'review.sh'], capture_output=True, text=True)
        self.assertEqual(old_check.returncode, 0)
        self.assertIn(str(other.pid), old_check.stdout.splitlines(), 'old global assertion must hit the foreign live reviewer')
        self.assertEqual(self.checker.wait_exited(own_pids), {})
        self.assertIsNone(other.poll(), 'foreign reviewer must remain alive throughout the check')

    def test_own_surviving_child_is_still_detected_after_parent_exits(self):
        own, pids = self.fixture('leaking')
        recorded = self.checker.read_fixture_pids(pids)
        own.kill()
        own.wait(timeout=3)
        live = self.checker.wait_exited(pids, timeout=.1)
        self.assertEqual(set(live), recorded - {own.pid})

    def test_real_kill_tree_terminates_recorded_fixture_parent_and_child(self):
        _, _other_pids = self.fixture('other-live')
        source = (ROOT / 'codexc-loop').read_text()
        fixture_function = source[source.index('it_hanging_fixture()'):source.index('\nit_assert_fixture_exited()')]
        pids, script = self.root / 'actual.pids', self.root / 'actual-review.sh'
        body = ('. ' + shlex.quote(str(ROOT / 'ck-common.sh')) + '\n' + fixture_function + '\n' +
                'it_hanging_fixture ' + shlex.quote(str(script)) + ' ' + shlex.quote(str(pids)) + ' review\n' +
                shlex.quote(str(script)) + ' </dev/null &\nfixture=$!\n' +
                'for ((n=0; n<60; n++)); do [ -s ' + shlex.quote(str(pids)) + ' ] && break; sleep .05; done\n' +
                'kill_tree "$fixture"\nwait "$fixture" 2>/dev/null\nexit 0\n')
        with (self.root / 'actual.log').open('w') as output:
            runner = subprocess.Popen(['/bin/bash', '-c', body], stdin=subprocess.DEVNULL,
                                      stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            self.children.append(runner)
            self.assertEqual(runner.wait(timeout=5), 0)
        self.assertTrue(pids.exists(), (self.root / 'actual.log').read_text() + '\nfixture=' + (script.read_text() if script.exists() else 'missing'))
        self.assertEqual(self.checker.wait_exited(pids), {})

    def test_missing_or_incomplete_fixture_record_cannot_pass(self):
        with self.assertRaises(OSError):
            self.checker.wait_exited(self.root / 'missing')
        pids = self.root / 'incomplete'
        pids.write_text(str(os.getpid()) + '\n')
        with self.assertRaises(ValueError):
            self.checker.wait_exited(pids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
