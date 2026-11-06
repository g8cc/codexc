#!/usr/bin/env python3
"""Offline startup, ownership and configuration regressions; no real provider calls."""
import json, os, pathlib, shlex, subprocess, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = pathlib.Path(os.environ.get('CODEXC_TEST_SOURCE', ROOT / 'codexc')).read_text()
FUNCTIONS = SOURCE.split('# ---- internal: standalone watcher entry')[0]

class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-startup-')
        self.addCleanup(self.tmp.cleanup)
        self.p = pathlib.Path(self.tmp.name).resolve()
        (self.p/'home').mkdir(); (self.p/'bin').mkdir()
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('CODEXC_', 'CODEX_', 'TMUX'))}
        self.env.update(HOME=str(self.p/'home'), CODEX_HOME=str(self.p/'home'), CODEXC_NOTIFY='0', CODEXC_LOOP_NOTIFY='0', PATH=str(self.p/'bin')+':'+os.environ['PATH'])
    def bash(self, code, timeout=10):
        return subprocess.run(['/bin/bash','-c',FUNCTIONS+'\n'+code,str(ROOT/'codexc')], cwd=self.p, env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    def mock(self,name,text):
        p=self.p/'bin'/name; p.write_text('#!/bin/bash\n'+text); p.chmod(0o755)
    def entry(self,args=(), **extra):
        self.mock('tmux', 'case "$1" in has-session) exit 1;; display-message) echo "%1";; esac\n')
        self.mock('codex','printf "%s\\n" "$@" > "'+str(self.p/'args')+'"\necho WORKER_STARTED\n')
        env=dict(self.env,TMUX='test',TMUX_PANE='%1',**extra)
        return subprocess.run(['/bin/bash','-c',SOURCE,str(ROOT/'codexc'),*args],cwd=self.p,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10)
    def test_missing_tmpdir_does_not_abort_startup(self):
        self.env.pop('TMPDIR',None)
        r=self.bash('PWD=/project; watch_and_run() { :; }; spawn_watcher "$$" "%1"; echo STARTED')
        self.assertEqual(r.returncode,0,r.stderr); self.assertIn('STARTED',r.stdout)
    def test_all_tool_watchers_exist(self):
        r=self.bash('for t in claude pi opencode; do declare -F "watch_and_run_$t" || exit 1; done')
        self.assertEqual(r.returncode,0,r.stderr)
    def test_bogus_tool_rejected_after_flags(self):
        r=self.entry(['-T','typo']); self.assertNotEqual(r.returncode,0); self.assertIn('unsupported',r.stderr)
    def test_no_loop_explicitly_wins(self):
        self.mock('codexc-loop','touch "'+str(self.p/'loop-started')+'"\n')
        r=self.entry(['loop','--no-loop'],CODEXC_AUTO_YES='0')
        self.assertEqual(r.returncode,0,r.stderr); self.assertFalse((self.p/'loop-started').exists())
    def test_codex_alias_not_forwarded_as_argument(self):
        r=self.entry(['codex','--model','test'],CODEXC_AUTO_YES='0')
        self.assertEqual(r.returncode,0,r.stderr); self.assertEqual((self.p/'args').read_text().splitlines(),['--model','test'])
    def test_explicit_short_sandbox_never_bypassed(self):
        r=self.bash('has_explicit_auto_mode -sread-only'); self.assertEqual(r.returncode,0)
    def test_retry_partial_config_stays_valid(self):
        import tomllib
        cfg=self.p/'home/config.toml'; cfg.write_text('[model_providers.custom]\nname = "custom"\nstream_max_retries = 4\n')
        r=self.bash('ensure_retry_config'); self.assertEqual(r.returncode,0,r.stderr)
        data=tomllib.loads(cfg.read_text()); self.assertEqual(data['model_providers']['custom']['stream_max_retries'],4)
    def test_retry_config_without_final_newline(self):
        import tomllib
        cfg=self.p/'home/config.toml'; cfg.write_text('[model_providers.custom]')
        r=self.bash('ensure_retry_config'); self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(tomllib.loads(cfg.read_text())['model_providers']['custom']['request_max_retries'],8)
    def test_retry_config_header_inside_multiline_string(self):
        import tomllib
        cfg=self.p/'home/config.toml'; cfg.write_text('note = """\n[model_providers.custom]\nkeep me\n"""\n[model_providers.custom]\nname="custom"\n')
        before=tomllib.loads(cfg.read_text())
        r=self.bash('ensure_retry_config'); self.assertEqual(r.returncode,0,r.stderr)
        after=tomllib.loads(cfg.read_text()); self.assertEqual(after['note'],before['note']); self.assertEqual(after['model_providers']['custom']['request_max_retries'],8)
    def test_retry_config_with_earlier_nested_table(self):
        import tomllib
        cfg=self.p/'home/config.toml'; cfg.write_text('[model_providers.custom.http_headers]\nx="kept"\n[model_providers.custom]\nname="custom"\n')
        r=self.bash('ensure_retry_config'); self.assertEqual(r.returncode,0,r.stderr)
        custom=tomllib.loads(cfg.read_text())['model_providers']['custom']; self.assertEqual(custom['request_max_retries'],8); self.assertEqual(custom['http_headers'],{'x':'kept'})
    def test_semantically_existing_trust_not_duplicated(self):
        import tomllib
        cfg=self.p/'home/config.toml'; cfg.write_text("[projects.'"+str(self.p)+"']\ntrust_level = 'trusted'\n")
        r=self.bash('ensure_project_trust'); self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(len(tomllib.loads(cfg.read_text())['projects']),1)
    def test_inline_projects_never_breaks_startup(self):
        cfg=self.p/'home/config.toml'; cfg.write_text('projects = {}\n')
        r=self.bash('ensure_project_trust'); self.assertEqual(r.returncode,0,r.stderr); self.assertEqual(cfg.read_text(),'projects = {}\n')
    def test_bad_claude_config_preserved(self):
        cdir=self.p/'claude'; cdir.mkdir(); cfg=cdir/'.claude.json'; cfg.write_text('{invalid but recoverable')
        self.env['CLAUDE_CONFIG_DIR']=str(cdir)
        r=self.bash('seed_claude_trust'); self.assertNotEqual(r.returncode,0); self.assertEqual(cfg.read_text(),'{invalid but recoverable')
    def test_discovery_not_limited_to_six_other_projects(self):
        import time
        sessions=self.p/'home/sessions'; sessions.mkdir()
        own=sessions/'own.jsonl'; own.write_text(json.dumps({'payload':{'cwd':str(self.p)}})+'\n')
        for n in range(9):
            other=sessions/f'other{n}.jsonl'; other.write_text(json.dumps({'payload':{'cwd':f'/other{n}'}})+'\n'); os.utime(other,(time.time()+n,time.time()+n))
        r=self.bash('tmux() { echo 999999999; }; pgrep() { :; }; lsof() { :; }; watcher_find_rollout "%1"')
        self.assertEqual(r.stdout,str(own),r.stderr)
    def test_missing_pane_never_sends_scheduled_text(self):
        r=self.bash('tmux() { case "$1" in display-message) return 0;; send-keys) echo SENT;; esac; }; notify() { :; }; run_scheduler 1 "%404" "test"')
        self.assertNotIn('SENT',r.stdout)
    def test_stale_tmux_environment_creates_a_fresh_session(self):
        self.mock('tmux', 'case "$1" in has-session) exit 1;; new-session) touch created;; esac\n')
        self.mock('codex', 'exit 0\n')
        env=dict(self.env,TMUX='stale-server',TMUX_PANE='%404',CODEXC_AUTO_YES='0')
        r=subprocess.run([str(ROOT/'codexc')],cwd=self.p,env=env,text=True,capture_output=True,timeout=5)
        self.assertEqual(r.returncode,0,r.stderr);self.assertTrue((self.p/'created').exists())
    def test_existing_plain_shell_is_not_a_codexc_session(self):
        r=self.bash('tmux() { case "$1" in show-option) :;; display-message) echo bash;; esac; }; session_tool_matches project')
        self.assertNotEqual(r.returncode,0)
    def test_scheduler_recognizes_claude_busy(self):
        r=self.bash('CODEXC_TOOL=claude; tmux() { echo "ctrl+c to interrupt"; }; scheduler_pane_busy "%1"')
        self.assertEqual(r.returncode,0)
    def test_scheduler_refuses_plain_shell(self):
        r=self.bash('tmux() { case "$1" in display-message) echo "%1";; send-keys) echo SENT;; esac; }; run_scheduler 1 "%1" "touch unsafe"')
        self.assertNotEqual(r.returncode,0); self.assertNotIn('SENT',r.stdout)
    def test_stale_watcher_pid_never_kills_arbitrary_process(self):
        r=self.bash('mkdir -p .codingkeeper; echo 12345 > .codingkeeper/watcher.pid; kill() { echo "KILL $*" >> killed; }; watch_and_run() { :; }; spawn_watcher "$$" "%1"')
        self.assertFalse((self.p/'killed').exists())

    def test_real_tmux_starts_worker_in_requested_project(self):
        import pty, shutil, time
        real = shutil.which('tmux')
        if not real: self.skipTest('tmux unavailable')
        # A unique socket avoids the live server even when this test runs alone.
        socket_dir = tempfile.TemporaryDirectory(prefix='ck-tmux-',dir='/private/tmp')
        self.addCleanup(socket_dir.cleanup)
        sock = str(pathlib.Path(socket_dir.name)/'s')
        self.mock('tmux', 'exec '+shlex.quote(real)+' -S '+shlex.quote(sock)+' "$@"\n')
        env=dict(self.env,TERM='xterm-256color',CODEXC_AUTO_YES='0',CODEXC_POLL='1')
        env.pop('TMPDIR',None)
        marker=self.p/'started'
        inherited=self.p/'client-env'
        self.mock('codex','pwd -P > '+shlex.quote(str(marker))+'\nprintf "WORKER_STARTED\\n"\nprintf "%s\\n" "$CODEXC_NOTIFY" "$CODEXC_REVIEW_CMD" "$PI_DIR" "$CODEXC_NIGHT_IDLE" "$CODEXC_NIGHT_WINDOW" "$CODEXC_NIGHT_TZ" > '+shlex.quote(str(inherited))+'\nexec sleep 60\n')
        project=self.p/"project '空 格;$(touch OWNED)"; project.mkdir()
        def tmux(*args):
            return subprocess.run([str(self.p/'bin/tmux'),*args],env=env,text=True,capture_output=True,timeout=10)
        self.addCleanup(lambda: tmux('kill-server'))
        r=tmux('-f','/dev/null','new-session','-d','-s','unrelated','sleep 60')
        self.assertEqual(r.returncode,0,r.stderr)
        env.update(CODEXC_NOTIFY='0', CODEXC_REVIEW_CMD='review --specific', PI_DIR=str(self.p/'client-pi'), CODEXC_NIGHT_IDLE='723', CODEXC_NIGHT_WINDOW='01:00-07:00', CODEXC_NIGHT_TZ='Asia/Tokyo')
        master, slave=pty.openpty()
        child=subprocess.Popen([str(ROOT/'codexc'),'-n','startup-audit'],cwd=project,env=env,
                               stdin=slave,stdout=slave,stderr=slave,start_new_session=True)
        os.close(slave)
        try:
            end=time.monotonic()+10
            while time.monotonic()<end and not marker.exists() and child.poll() is None:
                time.sleep(.1)
            self.assertTrue(marker.exists(),tmux('capture-pane','-p','-t','=startup-audit:').stdout)
            self.assertEqual(marker.read_text().strip(),str(project))
            self.assertFalse((project/'OWNED').exists())
            self.assertEqual(inherited.read_text().splitlines(),['0','review --specific',str(self.p/'client-pi'),'723','01:00-07:00','Asia/Tokyo'])
            r=tmux('show-option','-p','-v','-t','=startup-audit:','@codexc_tool'); self.assertEqual(r.stdout.strip(),'codex', r.stderr + tmux('list-panes','-a','-F','#{pane_id} #{pane_current_command} #{@codexc_tool}').stdout + tmux('capture-pane','-p','-t','=startup-audit:').stdout)
            self.assertEqual(tmux('show-option','-p','-v','-t','=unrelated:','@codexc_tool').stdout.strip(),'')
        finally:
            tmux('kill-session','-t','=startup-audit')
            if child.poll() is None: child.terminate()
            os.close(master)
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)

    def test_concurrent_trust_updates_preserve_all_projects(self):
        import tomllib
        cfg=self.p/'home/config.toml'; cfg.write_text('model = "kept"\n')
        processes=[subprocess.Popen(['python3',str(ROOT/'ck-config.py'),'codex',str(cfg),'trust',f'/p/{n}'],env=self.env) for n in range(12)]
        self.assertEqual([p.wait(timeout=10) for p in processes],[0]*12)
        data=tomllib.loads(cfg.read_text()); self.assertEqual(len(data['projects']),12); self.assertEqual(data['model'],'kept')

if __name__=='__main__': unittest.main(verbosity=2)
