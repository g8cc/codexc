#!/usr/bin/env python3
"""Run the harness with a private home and tmux socket, never the user's server."""
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[1]
base = Path(tempfile.mkdtemp(prefix='ck-tests-', dir='/private/tmp'))
print(f'Test artifacts: {base}', flush=True)
env = {k:v for k,v in os.environ.items() if not k.startswith(('CODEXC_', 'CODEX_', 'TMUX', 'CK_TEST_'))}
env.update(CK_TEST_ISOLATED='1', CK_TEST_ARTIFACTS=str(base), HOME=str(base/'home'), TMPDIR=str(base/'tmp')+'/',
           CODEX_HOME=str(base/'home/.codex'), CLAUDE_CONFIG_DIR=str(base/'home/.claude'),
           PI_DIR=str(base/'home/.pi'), OPENCODE_DATA_DIR=str(base/'home/.opencode'),
           CODEXC_LOOP_NOTIFY='0', CODEXC_NOTIFY='0', CODEXC_AUTO_RESUME='0', CODEXC_REVIEW_PARALLEL='0',
           GIT_AUTHOR_NAME='Codexc Test', GIT_AUTHOR_EMAIL='codexc-test@example.invalid',
           GIT_COMMITTER_NAME='Codexc Test', GIT_COMMITTER_EMAIL='codexc-test@example.invalid',
           SWIFT_MODULECACHE_PATH=os.environ.get('CK_SWIFT_TEST_CACHE', str(base/'swift-cache')), CLANG_MODULE_CACHE_PATH=os.environ.get('CK_CLANG_TEST_CACHE', str(base/'clang-cache')))
for name in ['home/.codex/bin', 'tmp', 'bin']:
    (base/name).mkdir(parents=True, exist_ok=True)
shutil.copy2(root/'tmux.conf',base/'home/.tmux.conf')
(base/'home/.codex/bin/sync-prefix2.sh').symlink_to(root/'sync-prefix2.sh')
real_tmux = shutil.which('tmux')
if not real_tmux:
    sys.exit('tmux is required for the full harness')
wrapper = base/'bin/tmux'
wrapper.write_text('#!/bin/bash\nexec '+shlex.quote(real_tmux)+' -S '+shlex.quote(str(base/'tmux.sock'))+' "$@"\n')
wrapper.chmod(0o755)
# Tests publish status but must never display desktop notifications.
notify=base/'bin/osascript'; notify.write_text('#!/bin/bash\nexit 0\n'); notify.chmod(0o755)
env['PATH'] = str(base/'bin')+':'+str(root)+':'+env['PATH']
child=None
def interrupted(_signum, _frame):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, interrupted)
try:
    child=subprocess.Popen([str(root/'tests/run-all'),*sys.argv[1:]],env=env,start_new_session=True)
    code=child.wait()
except KeyboardInterrupt:
    code=130
finally:
    if child:
        # Each run owns this process group, including any orphaned fake workers.
        try: os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            child.poll()  # Reap the group leader before Darwin probes a zombie-only group.
            try: os.killpg(child.pid,0)
            except (ProcessLookupError, PermissionError): break
            time.sleep(.05)
        try: os.killpg(child.pid,signal.SIGKILL)
        except (ProcessLookupError, PermissionError): pass
        child.wait(timeout=3)
    subprocess.run([str(wrapper),'kill-server'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL, timeout=5)
sys.exit(code)
