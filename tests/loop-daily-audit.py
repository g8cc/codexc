#!/usr/bin/env python3
"""Behavioral regressions for TUI freshness and daily resume (no APIs/tmux server)."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LoopDailyAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-loop-audit-")
        self.world = Path(self.tmp.name)
        (self.world / ".codingkeeper").mkdir()
        (self.world / "sessions").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def shell(self, script, body, **env):
        path = ROOT / script
        source = path.read_text()
        marker = "# ---- dispatch" if script == "codexc-loop" else '\ncase "${1:-run}" in'
        source = source.rsplit(marker, 1)[0]
        config = dict(os.environ, CODEX_HOME=str(self.world), CODEXC_LOOP_NOTIFY="0",
                      CODEXC_NOTIFY="0", CODEXC_LOOP_IDLE="0", CODEXC_BANNER="0")
        config.update(env)
        run = subprocess.run(["bash", "-c", source + "\n" + body, str(path)],
                             cwd=self.world, env=config, capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        return run.stdout.strip()

    def write_rollout(self, records):
        path = self.world / "rollout.jsonl"
        path.write_text("".join(json.dumps(x) + "\n" for x in records))
        return path

    @staticmethod
    def done(text="TASK_RESULT: DONE"):
        return {"payload": {"type": "task_complete", "last_agent_message": text}}

    def test_empty_baseline_is_single_number(self):
        self.write_rollout([])
        self.assertEqual(self.shell("codexc-loop", 'terminal_count rollout.jsonl'), "0")

    def test_codex_new_turn_cannot_reuse_previous_completion(self):
        self.write_rollout([self.done(), {"payload": {"type": "task_started"}}])
        self.assertEqual(self.shell("codexc-loop", 'turn_status rollout.jsonl .codingkeeper/msg'), "none")

    def test_codex_aborted_turn_is_error(self):
        self.write_rollout([self.done(), {"payload": {"type": "turn_aborted"}}])
        self.assertEqual(self.shell("codexc-loop", 'turn_status rollout.jsonl .codingkeeper/msg'), "error")

    def test_claude_tool_call_is_not_clean_completion(self):
        self.write_rollout([
            {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "TASK_RESULT: DONE"}]}},
            {"type": "user", "message": {"content": "fix"}},
            {"type": "assistant", "message": {"stop_reason": "tool_use", "content": [{"type": "text", "text": "I will fix"}, {"type": "tool_use"}]}}
        ])
        self.assertEqual(self.shell("codexc-loop", 'turn_status_claude rollout.jsonl .codingkeeper/msg'), "none")

    def test_claude_sidechain_does_not_refresh_old_completion(self):
        first = {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "TASK_RESULT: DONE"}]}}
        path = self.write_rollout([first])
        baseline = path.stat().st_size
        with path.open("a") as fh:
            fh.write(json.dumps(dict(first, isSidechain=True)) + "\n")
        self.assertEqual(self.shell("codexc-loop", 'turn_status_claude rollout.jsonl .codingkeeper/msg >/dev/null; cat .codingkeeper/msg.tok'), str(baseline))

    def test_pi_tool_call_is_not_clean_completion(self):
        self.write_rollout([
            {"type": "message", "message": {"role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "TASK_RESULT: DONE"}]}},
            {"type": "message", "message": {"role": "assistant", "stopReason": "toolUse", "content": []}}
        ])
        self.assertEqual(self.shell("codexc-loop", 'turn_status_pi rollout.jsonl .codingkeeper/msg'), "none")

    def test_fast_completion_is_accepted(self):
        self.write_rollout([])
        (self.world / ".codingkeeper/queue.md").write_text("## ready\n- [ ] task\n")
        output = self.shell("codexc-loop", r'''
notify() { :; }
banner_set() { :; }
sleep() { :; }
pane_idle() { return 0; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() { iterations=$((iterations+1)); [ "$iterations" -lt 8 ]; }
feed_msg() { printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE"}}' >> rollout.jsonl; }
gate_run() { return 0; }
review_run() { printf 0; }
run_driver audit
cat .codingkeeper/journal 2>/dev/null || true
''')
        self.assertIn("accepted after", output)

    def test_refeed_requires_new_completion(self):
        self.write_rollout([])
        (self.world / ".codingkeeper/queue.md").write_text("## ready\n- [ ] task\n")
        output = self.shell("codexc-loop", r'''
notify() { :; }
banner_set() { :; }
sleep() { :; }
pane_idle() { return 0; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() {
 iterations=$((iterations+1))
 if [ "$iterations" = 2 ]; then printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE"}}' >> rollout.jsonl; fi
 [ "$iterations" -lt 12 ]
}
feeds=0
feed_msg() {
 feeds=$((feeds+1))
 if [ "$feeds" -gt 1 ]; then printf '%s\n' '{"payload":{"type":"token_count"}}' >> rollout.jsonl; fi
}
gate_run() { return 0; }
review_run() {
 if [ ! -e .codingkeeper/reviewed ]; then touch .codingkeeper/reviewed; printf 1; else printf 0; fi
}
review_tail() { printf bug; }
run_driver audit
if [ -f .codingkeeper/journal ]; then cat .codingkeeper/journal; fi
''')
        self.assertNotIn("accepted after", output)

    def test_discovery_does_not_drop_older_active_project(self):
        for i in range(20):
            path = self.world / "sessions" / (str(i) + ".jsonl")
            path.write_text(json.dumps({"payload": {"type": "session_meta", "cwd": str(self.world) if i == 0 else "/another/" + str(i)}}) + "\n")
            os.utime(path, (100 + i, 100 + i))
        output = self.shell("codexc-loop", 'tmux() { printf "%s" "$PWD"; }; find_rollout audit')
        self.assertEqual(output, str(self.world / "sessions/0.jsonl"))

    def test_daily_error_completion_is_rescue_candidate(self):
        self.write_rollout([{"payload": {"type": "task_complete", "error": {"message": "stream disconnected"}}}])
        encoded = __import__("base64").b64encode(str(self.world / "rollout.jsonl").encode()).decode()
        self.assertEqual(self.shell("codexc-daily", 'last_turn_state "$AUDIT_ROLLOUT"', AUDIT_ROLLOUT=encoded), "died")

    def test_daily_malformed_rollout_is_unknown(self):
        self.write_rollout([{"payload": ["malformed"]}, None])
        encoded = __import__("base64").b64encode(str(self.world / "rollout.jsonl").encode()).decode()
        self.assertEqual(self.shell("codexc-daily", 'last_turn_state "$AUDIT_ROLLOUT"', AUDIT_ROLLOUT=encoded), "died")

    def test_opencode_sparse_sequences_use_sequence_baseline(self):
        import sqlite3
        with sqlite3.connect(self.world / "opencode.db") as db:
            db.execute("CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)")
            db.execute("INSERT INTO session_message VALUES ('s','assistant',100,'{}')")
        self.assertEqual(self.shell("codexc-loop", 'terminal_count s', CODEXC_TOOL="opencode", OPENCODE_DATA_DIR=str(self.world)), "100")

    def test_opencode_database_path_with_uri_characters(self):
        import sqlite3
        for dirname in ('data?mode=other', 'data#fragment', 'data % 中文'):
            with self.subTest(dirname=dirname):
                folder = self.world / dirname
                folder.mkdir()
                with sqlite3.connect(folder / 'opencode.db') as db:
                    db.execute('CREATE TABLE session_v2 (id TEXT, directory TEXT, time_updated INTEGER)')
                    db.execute('INSERT INTO session_v2 VALUES (?,?,?)', ('s', str(self.world), 1))
                    db.execute('CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)')
                    db.execute('INSERT INTO session_message VALUES (?,?,?,?)',
                               ('s', 'assistant', 7, json.dumps(dict(finish='stop', content=[dict(type='text', text='TASK_RESULT: DONE')]))))
                env = dict(CODEXC_TOOL='opencode', OPENCODE_DATA_DIR=str(folder))
                self.assertEqual(self.shell('codexc-loop', 'opencode_active_session "$PWD"', **env), 's')
                self.assertEqual(self.shell('codexc-loop', 'turn_status_opencode s .codingkeeper/msg', **env), 'clean')
                self.assertEqual((self.world / '.codingkeeper/msg').read_text(), 'TASK_RESULT: DONE')

    def test_opencode_in_place_stream_completion_changes_cache_key(self):
        import sqlite3
        path = self.world / "opencode.db"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)")
            db.execute("INSERT INTO session_message VALUES ('s','assistant',1,'{}')")
        before = self.shell("codexc-loop", 'rollout_size s', CODEXC_TOOL="opencode", OPENCODE_DATA_DIR=str(self.world))
        with sqlite3.connect(path) as db:
            db.execute('UPDATE session_message SET data=?', (json.dumps({"finish":"stop"}),))
        after = self.shell("codexc-loop", 'rollout_size s', CODEXC_TOOL="opencode", OPENCODE_DATA_DIR=str(self.world))
        self.assertNotEqual(before, after)

    def daily_stub(self, command="codex", tool="codex"):
        return self.shell("codexc-daily", r'''
notify() { :; }
sleep() { :; }
latest_rollout() { printf ignored; }
latest_cwd() { printf '%s.' "$PWD"; }
last_turn_state() { printf died; }
resolve_session_name() { printf audit; }
send_text() { printf SENT; }
tmux() {
 case "$*" in
  *'#{session_path}'*|*'#{pane_current_path}'*) printf '%s' "$PWD" ;;
  *'#{pane_id}'*) printf '%%1' ;;
  *'#{pane_current_command}'*) printf '%s' "$AUDIT_COMMAND" ;;
  *'@codexc_tool'*) printf '%s' "$AUDIT_TOOL" ;;
  *) return 0 ;;
 esac
}
run_now
''', CODEXC_DAILY_IDLE="0", AUDIT_COMMAND=command, AUDIT_TOOL=tool)

    def test_daily_never_types_into_shell(self):
        self.assertNotIn("SENT", self.daily_stub(command="bash"))

    def test_daily_never_types_into_other_tool(self):
        self.assertNotIn("SENT", self.daily_stub(tool="claude"))

    def test_daily_can_resume_verified_codex(self):
        self.assertIn("SENT", self.daily_stub())

    def test_long_turn_can_finish_after_stall_threshold(self):
        self.write_rollout([])
        (self.world / ".codingkeeper/queue.md").write_text("## ready\n- [ ] task\n")
        (self.world / "clock").write_text("100")
        output = self.shell("codexc-loop", r'''
notify() { :; }
banner_set() { :; }
sleep() { :; }
date() { if [ "$1" = +%s ]; then cat clock; else command date "$@"; fi; }
pane_idle() { [ "$iterations" != 2 ]; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() {
 iterations=$((iterations+1))
 case "$iterations" in
  2) printf 106 > clock; printf '%s\n' '{"payload":{"type":"token_count"}}' >> rollout.jsonl ;;
  3) printf 112 > clock; printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE"}}' >> rollout.jsonl ;;
 esac
 [ "$iterations" -lt 9 ]
}
feed_msg() { :; }
gate_run() { return 0; }
review_run() { printf 0; }
run_driver audit
cat .codingkeeper/journal 2>/dev/null || true
''', CODEXC_LOOP_STALL="5", CODEXC_TURN_TIMEOUT="30")
        self.assertIn("accepted after", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
