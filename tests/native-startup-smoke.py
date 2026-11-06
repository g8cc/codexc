#!/usr/bin/env python3
"""Optional native Codex TUI smoke (not part of the offline regression suite).

Requires the installed Codex CLI and macOS tmux. Uses a private HOME/socket and
answers terminal capability queries; never submits a model task or signs in.
Codex may initialize its own daemon package. The three final screens and raw
terminal streams are retained under the printed artifact directory.
"""
import fcntl,os,pathlib,pty,select,shlex,shutil,struct,subprocess,tempfile,termios,time
root=pathlib.Path(__file__).resolve().parents[1]
p=pathlib.Path(tempfile.mkdtemp(prefix='ck-native-tty-',dir='/private/tmp'))
(p/'bin').mkdir();(p/'home').mkdir();(p/'project').mkdir()
real_tmux=shutil.which('tmux');real_codex=shutil.which('codex')
wrapper=p/'bin/tmux';wrapper.write_text('#!/bin/bash\nexec '+shlex.quote(real_tmux)+' -S '+shlex.quote(str(p/'socket'))+' "$@"\n');wrapper.chmod(0o755)
env={k:v for k,v in os.environ.items() if not k.startswith(('CODEXC_','CODEX_','TMUX'))}
env.update(HOME=str(p/'home'),CODEX_HOME=str(p/'home'),CODEXC_AUTO_YES='0',CODEXC_NOTIFY='0',CODEXC_LOOP_NOTIFY='0',PATH=str(p/'bin')+':'+os.environ['PATH'],TERM='xterm-256color')
print('Artifacts:',p,flush=True)
results=[]
for mode,args in [('direct',[real_codex,'--no-daemon']),('wrapped',[str(root/'codexc'),'--no-daemon']),('daemon',[str(root/'codexc')])]:
 master,slave=pty.openpty();fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',35,110,0,0))
 child=None
 try:
  subprocess.run([str(wrapper),'-f','/dev/null','new-session','-d','-s',mode,'-x','110','-y','35','-c',str(p/'project'),shlex.join(args)],env=env,check=True)
  child=subprocess.Popen([str(wrapper),'attach','-t','='+mode],env=env,stdin=slave,stdout=slave,stderr=slave,start_new_session=True);os.close(slave)
  deadline=time.monotonic()+25;raw=b'';screen=''
  while time.monotonic()<deadline:
   ready,_,_=select.select([master],[],[],.15)
   if ready:
    try: chunk=os.read(master,65536)
    except OSError:break
    raw+=chunk
    responses={b'\x1b[6n':b'\x1b[1;1R',b'\x1b[c':b'\x1b[?1;2c',b'\x1b[>c':b'\x1b[>0;0;0c',b'\x1b[?u':b'\x1b[?0u',b'\x1b]11;?':b'\x1b]11;rgb:0000/0000/0000\x1b\\',b'\x1b]10;?':b'\x1b]10;rgb:ffff/ffff/ffff\x1b\\'}
    for query,answer in responses.items():
     if query in chunk:os.write(master,answer)
   screen=subprocess.run([str(wrapper),'capture-pane','-p','-t',mode],env=env,text=True,capture_output=True).stdout
   if 'Codex' in screen or 'Sign in' in screen or 'OpenAI' in screen:break
  (p/(mode+'.txt')).write_text(screen);(p/(mode+'.raw')).write_bytes(raw)
  ok=any(label in screen for label in ('Ask Codex', 'Sign in', 'sign in', 'Welcome to Codex', 'trust this'));results.append(ok)
  print(mode, 'VISIBLE' if ok else 'BLANK',repr(screen.strip()[:700]),flush=True)
 finally:
  subprocess.run([str(wrapper),'kill-session','-t','='+mode],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  os.close(master)
  if child and child.poll() is None:child.terminate()
  if child:
   try:child.wait(timeout=2)
   except subprocess.TimeoutExpired:child.kill();child.wait()
try:
 subprocess.run([real_codex,'app-server','daemon','stop'],env=env,timeout=10,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
except subprocess.TimeoutExpired:pass
subprocess.run([str(wrapper),'kill-server'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
raise SystemExit(0 if all(results) else 1)
