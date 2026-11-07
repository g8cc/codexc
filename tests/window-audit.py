#!/usr/bin/env python3
"""Offline active-window policy and subprocess boundary regressions."""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo('Asia/Shanghai')

def epoch(local):
    return dt.datetime.fromisoformat(local).replace(tzinfo=TZ).timestamp()

class ProcessWindowAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-window-audit-')
        self.world = Path(self.tmp.name)
        (self.world/'.codingkeeper').mkdir()
        self.env = dict(os.environ, CODEX_HOME=str(self.world), CODEXC_ACTIVE_WINDOW='23:00-09:00',
                        CODEXC_ACTIVE_TZ='Asia/Shanghai', CODEXC_LOOP_NOTIFY='0')

    def tearDown(self):
        self.tmp.cleanup()

    def shell(self, body, timeout=10):
        script = 'set -u\n. '+shlex.quote(str(ROOT/'ck-common.sh'))+'\n'+body
        result = subprocess.run(['bash','-c',script], cwd=self.world, env=self.env, text=True,
                                capture_output=True, timeout=timeout, start_new_session=True)
        return result

    def test_review_refuses_closed_window_before_process_launch(self):
        result = self.shell('''
ck_window_check() { CK_WINDOW_REASON=outside_window; return 125; }
CODEXC_REVIEW_TIMEOUT=2
CODEXC_REVIEW_CMD="touch invoked; printf 'BUGS: 0\\n'"
review_run task .codingkeeper/review
printf ':rc=%s' "$?"
''')
        self.assertEqual(result.stdout, 'window-closed:rc=125')
        self.assertFalse((self.world/'invoked').exists())

    def test_gate_refuses_closed_window_before_process_launch(self):
        (self.world/'.codingkeeper/gate.sh').write_text('#!/bin/bash\ntouch invoked\n')
        result = self.shell('''
ck_window_check() { CK_WINDOW_REASON=outside_window; return 125; }
CODEXC_GATE_TIMEOUT=2
gate_run .codingkeeper/gate
printf 'rc=%s' "$?"
''')
        self.assertEqual(result.stdout, 'rc=125')
        self.assertFalse((self.world/'invoked').exists())

    def time_shim(self):
        return r'''
python3() {
 if [ "$1" = "$CK_COMMON_DIR/ck-window.py" ]; then
  command python3 "$@" --now "$(cat clock)"
 else
  command python3 "$@"
 fi
}
'''

    def test_shared_check_sets_deadline_and_next_open(self):
        (self.world/'clock').write_text(str(epoch('2026-11-05T23:00:00')))
        result = self.shell(self.time_shim() + 'ck_window_check; printf "%s:%s:%s:%s" "$?" "$CK_WINDOW_ALLOWED" "$CK_WINDOW_DEADLINE" "$CK_WINDOW_NEXT_OPEN"')
        self.assertEqual(result.stdout, f"0:1:{int(epoch('2026-11-06T09:00:00'))}:{int(epoch('2026-11-06T23:00:00'))}")

    def test_weekend_exemption_all_day(self):
        # 周末套餐全天开放 (2026-11-07 用户确认): Sat/Sun 不受 23:00-09:00 窗口限制
        cases = [
            ('2026-11-07T14:00:00', True, 'weekend'),   # Saturday
            ('2026-11-08T02:00:00', True, 'weekend'),   # Sunday 凌晨
            ('2026-11-08T14:00:00', True, 'weekend'),   # Sunday
            ('2026-11-08T23:30:00', True, 'weekend'),   # Sunday 深夜
        ]
        for local, want_allowed, want_reason in cases:
            (self.world/'clock').write_text(str(epoch(local)))
            result = self.shell(self.time_shim() + 'ck_window_check; printf "%s:%s" "$CK_WINDOW_ALLOWED" "$CK_WINDOW_REASON"')
            self.assertEqual(result.stdout, f"1:{want_reason}", msg=local)

    def test_weekday_window_still_applies(self):
        cases = [
            ('2026-11-09T08:00:00', '1', 'allowed'),        # 周一 overnight 尾
            ('2026-11-09T14:00:00', '0', 'outside_window'),  # 周一白天禁
            ('2026-11-06T23:30:00', '1', 'allowed'),        # 周五 overnight 头
        ]
        for local, want_allowed, want_reason in cases:
            (self.world/'clock').write_text(str(epoch(local)))
            result = self.shell(self.time_shim() + 'ck_window_check; printf "%s:%s" "$CK_WINDOW_ALLOWED" "$CK_WINDOW_REASON"')
            self.assertEqual(result.stdout, f"{want_allowed}:{want_reason}", msg=local)

    def test_shared_check_reports_next_window_at_close(self):
        (self.world/'clock').write_text(str(epoch('2026-11-06T09:00:00')))
        result = self.shell(self.time_shim() + 'ck_window_check; printf "%s:%s:%s" "$?" "$CK_WINDOW_REASON" "$CK_WINDOW_NEXT_OPEN"')
        self.assertEqual(result.stdout, f"125:outside_window:{int(epoch('2026-11-06T23:00:00'))}")

    def test_unset_policy_does_not_restrict_other_tools(self):
        result = self.shell('unset CODEXC_ACTIVE_WINDOW; ck_window_check; printf "%s:%s:%s" "$?" "$CK_WINDOW_REASON" "$CK_WINDOW_DEADLINE"')
        self.assertEqual(result.stdout, '0:disabled:0')

    def test_invalid_configuration_closes_gate(self):
        self.env['CODEXC_ACTIVE_TZ']='Not/A_Timezone'
        result = self.shell('ck_window_check; printf "%s:%s" "$?" "$CK_WINDOW_REASON"')
        self.assertEqual(result.stdout, '125:invalid_timezone')

    def test_invalid_helper_responses_cannot_open_gate(self):
        for answer in ('oops', '1\t0\t0\tallowed', '1\t1000\t2000\toutside_window',
                       '1\t999999999999999999999\t2\tallowed', '1\t10:20\t2\tallowed',
                       '1\t1000\t2000\tallowed\n1\t1000\t2000\tallowed'):
            (self.world/'answer').write_text(answer)
            with self.subTest(answer=answer):
                result=self.shell('python3() { cat answer; }; ck_window_check; printf "%s" "$?"')
                self.assertEqual(result.stdout, '125')

    def test_failed_helper_cannot_return_successful_verdict(self):
        result=self.shell(r'''
python3() { printf '1\t1000\t2000\tallowed\n'; return 1; }
ck_window_check; printf '%s' "$?"
''')
        self.assertEqual(result.stdout, '125')

    def running_fixture(self, *, halt=False):
        (self.world/'clock').write_text(str(epoch('2026-11-06T08:59:59')))
        script=self.world/'worker.sh'
        action='touch .codingkeeper/loop.halt' if halt else f"printf '%s' {int(epoch('2026-11-06T09:00:00'))} > clock"
        script.write_text('#!/bin/bash\nsleep 30 &\nprintf "%s %s\\n" "$$" "$!" >> pids\n'+action+'\nwait\n')
        return script

    def assert_fixture_stopped(self):
        self.assertTrue((self.world/'pids').exists())
        for line in (self.world/'pids').read_text().splitlines():
            for pid in line.split():
                with self.assertRaises(ProcessLookupError, msg=f'fixture PID {pid} survived'):
                    os.kill(int(pid),0)

    def test_review_stops_process_tree_at_deadline(self):
        self.running_fixture()
        result=self.shell(self.time_shim()+r'''
CODEXC_REVIEW_TIMEOUT=20
CODEXC_REVIEW_CMD='bash worker.sh'
review_run task .codingkeeper/review
printf ':rc=%s' "$?"
''')
        self.assertEqual(result.stdout,'window-closed:rc=125',result.stderr)
        self.assert_fixture_stopped()

    def test_gate_stops_process_tree_at_deadline(self):
        self.running_fixture()
        (self.world/'.codingkeeper/gate.sh').write_text('exec bash worker.sh\n')
        result=self.shell(self.time_shim()+r'''
CODEXC_GATE_TIMEOUT=20
gate_run .codingkeeper/gate
printf 'rc=%s' "$?"
''')
        self.assertEqual(result.stdout,'rc=125',result.stderr)
        self.assert_fixture_stopped()

    def test_manual_halt_interrupts_review(self):
        self.running_fixture(halt=True)
        result=self.shell(self.time_shim()+r'''
CODEXC_REVIEW_TIMEOUT=20
CODEXC_REVIEW_CMD='bash worker.sh'
review_run task .codingkeeper/review
printf ':rc=%s' "$?"
''')
        self.assertEqual(result.stdout,'window-closed:rc=125',result.stderr)
        self.assert_fixture_stopped()
        self.assertTrue((self.world/'.codingkeeper/loop.halt').exists())

    def test_review_batch_preserves_window_stop_over_other_errors(self):
        result=self.shell(r'''
CODEXC_REVIEW_PASS=3
review_run() {
 case "$2" in
  *.1) printf window-closed; return 125 ;;
  *.2) printf timeout ;;
  *.3) printf parse-fail ;;
 esac
}
review_batch task .codingkeeper/review
printf ':rc=%s:%s' "$?" "$REVIEW_BATCH_RESULT"
''')
        self.assertIn(':rc=125:window-closed', result.stdout)

    def test_parallel_reviews_stop_at_deadline(self):
        self.running_fixture()
        result=self.shell(self.time_shim()+r'''
CODEXC_REVIEW_PASS=2
CODEXC_REVIEW_TIMEOUT=20
CODEXC_REVIEW_CMD='bash worker.sh'
review_batch task .codingkeeper/review
printf ':rc=%s:%s' "$?" "$REVIEW_BATCH_RESULT"
''')
        self.assertIn(':rc=125:window-closed',result.stdout,result.stderr)
        self.assert_fixture_stopped()

    def test_wait_status_and_heartbeat_keep_next_run_metadata(self):
        result=self.shell('status_write waiting zcode 0 0 waiting_window 123456; status_touch')
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads((self.world/'.codingkeeper/status.json').read_text())
        self.assertEqual(data['phase'],'waiting_window')
        self.assertEqual(data['next_run_at'],123456)
        self.assertFalse(data['active'])

    def test_old_status_calls_keep_task_phase_and_zero_next_run(self):
        result=self.shell('status_write legacy codex 1 123; status_touch')
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads((self.world/'.codingkeeper/status.json').read_text())
        self.assertEqual(data['phase'],'legacy')
        self.assertEqual(data['next_run_at'],0)


class PureWindowAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('window_policy',ROOT/'ck-window.py')
        cls.policy=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.policy)

    def evaluate(self, value):
        return self.policy.evaluate('23:00-09:00','Asia/Shanghai',epoch(value))

    def test_half_open_midnight_boundaries(self):
        for value,allowed in [('2026-11-05T22:59:59.999',False),('2026-11-05T23:00:00',True),
                              ('2026-11-06T00:00:00',True),('2026-11-06T08:59:59.999',True),
                              ('2026-11-06T09:00:00',False),('2026-11-06T22:59:59',False)]:
            with self.subTest(value=value):
                self.assertEqual(self.evaluate(value)['allowed'],allowed)

    def test_deadline_is_next_morning_and_next_open_is_tonight(self):
        result=self.evaluate('2026-11-06T01:30:00')
        self.assertEqual(result['deadline'],epoch('2026-11-06T09:00:00'))
        self.assertEqual(result['next_open'],epoch('2026-11-06T23:00:00'))

    def test_year_and_leap_day_rollovers(self):
        for local,end in [('2026-12-31T23:00:00','2027-01-01T09:00:00'),('2028-02-28T23:00:00','2028-02-29T09:00:00')]:
            self.assertEqual(self.evaluate(local)['deadline'],epoch(end))

    def test_daytime_window_uses_same_date(self):
        result=self.policy.evaluate('09:00-17:00','Asia/Shanghai',epoch('2026-11-05T09:00:00'))
        self.assertTrue(result['allowed'])
        self.assertEqual(result['deadline'],epoch('2026-11-05T17:00:00'))
        self.assertFalse(self.policy.evaluate('09:00-17:00','Asia/Shanghai',epoch('2026-11-05T17:00:00'))['allowed'])

    def test_policy_timezone_does_not_follow_host_clock(self):
        # 23:00 UTC is 07:00 next day in Shanghai; the opening timestamps differ.
        instant=epoch('2026-11-06T10:00:00')
        self.assertFalse(self.policy.evaluate('23:00-09:00','Asia/Shanghai',instant)['allowed'])
        self.assertTrue(self.policy.evaluate('23:00-09:00','UTC',instant)['allowed'])

    def test_invalid_windows_fail_closed(self):
        for value in ('23:00','23:00-24:00','25:00-09:00','23:61-09:00','23:00-23:00',
                      '23:00-9:00',' 23:00-09:00','23:00-09:00\n',True):
            with self.subTest(value=value):
                result=self.policy.evaluate(value,'Asia/Shanghai',0)
                self.assertFalse(result['allowed'])
                self.assertEqual(result['reason'],'invalid_window')

    def test_invalid_clocks_and_timezone_fail_closed(self):
        for value in ('NaN','Infinity','bad',1e100):
            self.assertFalse(self.policy.evaluate('23:00-09:00','Asia/Shanghai',value)['allowed'])
        self.assertEqual(self.policy.evaluate('23:00-09:00','../bad',0)['reason'],'invalid_timezone')

    def test_unconfigured_policy_is_unrestricted(self):
        for value in (None,''):
            self.assertEqual(self.policy.evaluate(value,'invalid',0),{'allowed':True,'deadline':0,'next_open':0,'reason':'disabled'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
