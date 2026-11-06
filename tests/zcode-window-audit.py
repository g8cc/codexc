#!/usr/bin/env python3
"""Offline ZCode execution-window regressions. Never invokes a real model."""
import json, os, shlex, signal, subprocess, tempfile, time, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def lib():
 s=(ROOT/'codexc-headless').read_text();s=s[:s.rindex('\ncase "${1:-}" in')]
 return '\n'.join('. '+shlex.quote(str(ROOT/'ck-common.sh')) if l.startswith('. "$(dirname') else l for l in s.splitlines())+'\n'
class WindowTests(unittest.TestCase):
 def run_case(self,body,timeout=10):
  with tempfile.TemporaryDirectory(prefix='ck-zcode-window-') as d:
   p=Path(d); (p/'.codingkeeper').mkdir();(p/'.codingkeeper/queue.md').write_text('## ready\n- [ ] task\n')
   env=dict(os.environ,HOME=str(p),CODEX_HOME=str(p/'home'),CODEXC_LOOP_NOTIFY='0',CODEXC_LOOP_IDLE='0',CODEXC_BANNER='0',CODEXC_ACTIVE_WINDOW='',CODEXC_AUTO_RESUME='1',CODEXC_REVIEW_CMD="printf 'BUGS: 0\\n'",CODEXC_HEADLESS_CMD="printf 'worker called\\n' >> calls; printf 'TASK_RESULT: DONE\\n'")
   script=lib()+'\nregister_project(){ :; }; notify(){ :; };\n'+body
   proc=subprocess.Popen(['/bin/bash','-c',script],cwd=p,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
   try:out,err=proc.communicate(timeout=timeout)
   except subprocess.TimeoutExpired:
    os.killpg(proc.pid,signal.SIGKILL);proc.communicate();self.fail('isolated fixture timed out')
   files={str(f.relative_to(p)):f.read_text(errors='replace') for f in p.rglob('*') if f.is_file() and not f.is_symlink() and f.stat().st_size<20000}
   return proc.returncode,out,err,files
 def test_outside_window_rejects_worker(self):
  rc,out,err,files=self.run_case('ck_window_check(){ CK_WINDOW_REASON=outside_window; CK_WINDOW_ALLOWED=0; return 125; }; headless_turn task .codingkeeper/out; echo "rc=$?"')
  self.assertIn('rc=125',out);self.assertNotIn('calls',files)
 def test_deadline_stops_running_worker(self):
  rc,out,err,files=self.run_case('''
ck_window_check(){ CK_WINDOW_DEADLINE=$(( $(date +%s) + 2 )); return 0; }
CODEXC_HEADLESS_CMD="echo started > calls; sleep 20; echo late > escaped"
headless_turn task .codingkeeper/out; echo "rc=$?"
''')
  self.assertIn('rc=125',out);self.assertIn('calls',files);self.assertNotIn('escaped',files)
 def test_manual_halt_stops_worker(self):
  rc,out,err,files=self.run_case('''
CODEXC_HEADLESS_CMD="echo started > calls; sleep 20; echo late > escaped"
(sleep 1; touch .codingkeeper/loop.halt) &
headless_turn task .codingkeeper/out; echo "rc=$?"
''')
  self.assertIn('rc=125',out);self.assertNotIn('escaped',files)
 def test_runner_waits_without_starting_worker(self):
  rc,out,err,files=self.run_case('''
ck_window_check(){ CK_WINDOW_REASON=outside_window; CK_WINDOW_ALLOWED=0; CK_WINDOW_NEXT_OPEN=$(( $(date +%s) + 600 )); return 125; }
sleep(){ cp .codingkeeper/status.json waiting.json; touch .codingkeeper/loop.halt; }
run_runner
''')
  self.assertEqual(rc,0,err);self.assertNotIn('calls',files)
  s=json.loads(files['waiting.json']);self.assertFalse(s['active']);self.assertEqual(s['phase'],'waiting_window');self.assertGreater(s['next_run_at'],time.time())
 def test_quota_waits_until_next_window_without_retry(self):
  rc,out,err,files=self.run_case('''
ck_window_check(){ CK_WINDOW_REASON=allowed; CK_WINDOW_ALLOWED=1; CK_WINDOW_DEADLINE=$(( $(date +%s) + 60 )); CK_WINDOW_NEXT_OPEN=$(( $(date +%s) + 600 )); return 0; }
headless_turn(){ echo call >> calls; printf 'CK_ERROR_CLASS: quota\\n' > "$2"; return 1; }
sleep(){ cp .codingkeeper/status.json waiting.json; touch .codingkeeper/loop.halt; }
run_runner
''')
  self.assertEqual(rc,0,err);self.assertEqual(files['calls'].count('call'),1)
  s=json.loads(files['waiting.json']);self.assertEqual(s['phase'],'waiting_quota');self.assertFalse(s['active']);self.assertIn('.codingkeeper/quota-until',files)
 def test_cutoff_never_accepts_done_or_runs_gate(self):
  rc,out,err,files=self.run_case('''
headless_turn(){ echo call >> calls; printf 'TASK_RESULT: DONE\\n' > "$2"; touch .codingkeeper/loop.halt; return 125; }
gate_run(){ echo gate >> gates; return 0; }
run_runner
''')
  self.assertEqual(rc,0,err);self.assertNotIn('gates',files);self.assertNotIn('.codingkeeper/journal',files)
 def test_backoff_is_not_active(self):
  rc,out,err,files=self.run_case('''
headless_turn(){ echo call >> calls; printf 'CK_ERROR_CLASS: unknown\\n' > "$2"; return 1; }
sleep(){ cp .codingkeeper/status.json waiting.json; touch .codingkeeper/loop.halt; }
run_runner
''')
  s=json.loads(files['waiting.json']);self.assertEqual(s['phase'],'backoff');self.assertFalse(s['active'])
 def test_invalid_quota_marker_blocks_execution(self):
  rc,out,err,files=self.run_case("printf 'not-an-epoch' > .codingkeeper/quota-until; run_runner")
  self.assertNotIn('calls',files);self.assertTrue('.codingkeeper/loop.halt' in files)
 def test_persisted_quota_blocks_restart(self):
  rc,out,err,files=self.run_case('''
now=$(date +%s); echo $((now + 600)) > .codingkeeper/quota-until
sleep(){ cp .codingkeeper/status.json waiting.json; touch .codingkeeper/loop.halt; }
run_runner
''')
  self.assertNotIn('calls',files);self.assertEqual(json.loads(files['waiting.json'])['phase'],'waiting_quota')
 def test_quota_marker_cannot_be_fifo_or_symlink(self):
  for setup in ("mkfifo .codingkeeper/quota-until", "echo 9999999999 > elsewhere; ln -s ../elsewhere .codingkeeper/quota-until"):
   with self.subTest(setup=setup):
    rc,out,err,files=self.run_case(setup+'; run_runner')
    self.assertNotIn('calls',files);self.assertIn('.codingkeeper/loop.halt',files)
 def test_quota_respects_auto_resume_disabled(self):
  rc,out,err,files=self.run_case('''
CODEXC_AUTO_RESUME=0
ck_window_check(){ CK_WINDOW_REASON=allowed; CK_WINDOW_ALLOWED=1; CK_WINDOW_DEADLINE=$(( $(date +%s) + 60 )); CK_WINDOW_NEXT_OPEN=$(( $(date +%s) + 600 )); return 0; }
headless_turn(){ echo call >> calls; printf 'CK_ERROR_CLASS: quota\\n' > "$2"; return 1; }
run_runner
''')
  self.assertEqual(files['calls'].count('call'),1);self.assertIn('.codingkeeper/loop.halt',files);self.assertNotIn('.codingkeeper/quota-until',files)
 def test_expired_quota_allows_one_new_turn(self):
  rc,out,err,files=self.run_case('''
echo 1 > .codingkeeper/quota-until
headless_turn(){ echo call >> calls; touch .codingkeeper/loop.halt; return 125; }
run_runner
''')
  self.assertIn('calls',files);self.assertNotIn('.codingkeeper/quota-until',files)
 def quota_during_repair(self, review=False, parallel=True):
  body=''' 
ck_window_check(){ CK_WINDOW_REASON=allowed; CK_WINDOW_ALLOWED=1; CK_WINDOW_DEADLINE=$(( $(date +%s) + 60 )); CK_WINDOW_NEXT_OPEN=$(( $(date +%s) + 600 )); return 0; }
headless_turn(){
 n=$(cat count 2>/dev/null || echo 0); echo $((n+1)) > count
 if [ "$n" = 0 ]; then printf 'TASK_RESULT: DONE\\n' > "$2"; return 0
 else printf 'CK_ERROR_CLASS: quota\\n' > "$2"; return 1; fi
}
sleep(){ cp .codingkeeper/status.json waiting.json; touch .codingkeeper/loop.halt; }
'''
  if review:
   body+='gate_run(){ return 0; }; review_batch(){ : > "$2"; return 1; }; review_run(){ : > "$2"; printf 1; };\n'
   body+='CODEXC_REVIEW_PARALLEL='+('1' if parallel else '0')+'\n'
  else:
   body+='gate_run(){ : > "$1"; return 1; };\n'
  rc,out,err,files=self.run_case(body+'run_runner')
  self.assertEqual(rc,0,err);self.assertEqual(files['count'].strip(),'2')
  self.assertIn('.codingkeeper/quota-until',files)
  self.assertNotIn('.codingkeeper/journal',files)
  self.assertIn('- [ ] task',files['.codingkeeper/queue.md'])
  status=json.loads(files['waiting.json'])
  self.assertEqual(status['phase'],'waiting_quota');self.assertFalse(status['active'])
 def test_quota_in_gate_repair_defers_to_next_window(self):
  self.quota_during_repair()
 def test_quota_in_review_repair_defers_to_next_window(self):
  for parallel in (True,False):
   with self.subTest(parallel=parallel):self.quota_during_repair(review=True,parallel=parallel)
 def test_cli_status_live_waiting_runner_is_never_burning(self):
  for phase,label in [('waiting_window','等待时段'),('waiting_quota','等待配额'),('backoff','等待重试')]:
   with self.subTest(phase=phase):
    rc,out,err,files=self.run_case('''
mkdir -p "$HOME/.codingkeeper"
printf '%s\\n' "$PWD" > "$HOME/.codingkeeper/projects"
printf '%s\\n' "$$" > .codingkeeper/loop.pid
status_write 'waiting' zcode 1 0 PHASE 1234567890
cmd_status
'''.replace('PHASE',phase))
    self.assertEqual(rc,0,err);self.assertIn(label,out)
    self.assertNotIn('🔥',out);self.assertNotIn('燃烧中',out);self.assertNotIn('任务执行中',out)
 def test_cli_status_live_idle_runner_is_not_burning(self):
  rc,out,err,files=self.run_case('''
mkdir -p "$HOME/.codingkeeper"
printf '%s\\n' "$PWD" > "$HOME/.codingkeeper/projects"
printf '%s\\n' "$$" > .codingkeeper/loop.pid
status_write 'idle' zcode 0 0
cmd_status
''')
  self.assertEqual(rc,0,err);self.assertIn('空闲',out);self.assertNotIn('🔥',out)
 def test_zcodec_run_sets_window_defaults(self):
  with tempfile.TemporaryDirectory(prefix='ck-zcodec-entry-') as d:
   p=Path(d);(p/'zcodec').write_bytes((ROOT/'zcodec').read_bytes());(p/'zcodec').chmod(0o755)
   hl=p/'codexc-headless';hl.write_text('#!/bin/bash\nprintf "%s|%s" "${CODEXC_ACTIVE_WINDOW:-missing}" "${CODEXC_ACTIVE_TZ:-missing}"\n');hl.chmod(0o755)
   env={k:v for k,v in os.environ.items() if not k.startswith('CODEXC_')}
   r=subprocess.run([str(p/'zcodec'),'run'],env=env,text=True,capture_output=True)
   self.assertEqual(r.stdout,'23:00-09:00|Asia/Shanghai')
 def test_zcodec_run_defaults_to_queue_only_and_requires_gate(self):
  with tempfile.TemporaryDirectory(prefix='ck-zcodec-safe-entry-') as d:
   p=Path(d);(p/'zcodec').write_bytes((ROOT/'zcodec').read_bytes());(p/'zcodec').chmod(0o755)
   hl=p/'codexc-headless';hl.write_text('#!/bin/bash\nprintf "%s|%s" "${CODEXC_LOOP_IDLE:-missing}" "${CODEXC_REQUIRE_GATE:-missing}"\n');hl.chmod(0o755)
   env={k:v for k,v in os.environ.items() if not k.startswith('CODEXC_')}
   r=subprocess.run([str(p/'zcodec'),'run'],env=env,text=True,capture_output=True)
   self.assertEqual(r.stdout,'0|1')
   r=subprocess.run([str(p/'zcodec'),'run'],env=dict(env,CODEXC_LOOP_IDLE='1',CODEXC_REQUIRE_GATE='0'),text=True,capture_output=True)
   self.assertEqual(r.stdout,'1|1')
if __name__=='__main__':unittest.main(verbosity=2)
