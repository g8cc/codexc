#!/usr/bin/env python3
"""Offline acceptance/locking regressions; no tmux server or provider required."""
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile

ROOT = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parent.parent))
FAILURES = []


def library():
    source = (ROOT / 'codexc-headless').read_text()
    source = source[:source.rindex('\ncase "${1:-}" in')]
    lines = source.splitlines()
    for n, line in enumerate(lines):
        if line.startswith('. "$(dirname'):
            lines[n] = '. ' + shlex.quote(str(ROOT / 'ck-common.sh'))
    return '\n'.join(lines) + '\n'


def run(name, body, check, timeout=15):
    with tempfile.TemporaryDirectory(prefix='ck-acceptance-') as directory:
        world = Path(directory)
        (world / '.codingkeeper').mkdir()
        (world / '.codingkeeper/queue.md').write_text('## ready\n- [ ] task\n')
        env = dict(os.environ, CODEX_HOME=str(world / 'codex-home'), CODEXC_LOOP_NOTIFY='0',
                   CODEXC_LOOP_IDLE='0', CODEXC_AUTO_RESUME='0', CODEXC_BANNER='0',
                   CODEXC_HEADLESS_CMD='true', TMPDIR=tempfile.gettempdir())
        script = library() + '\n' + body + '\n'
        process = subprocess.Popen(['/bin/bash', '-c', script], cwd=world, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            out, err = process.communicate(timeout=timeout)
            passed = check(process.returncode, out, err, world)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            out, err = process.communicate()
            passed = False
        if passed:
            print('PASS', name, flush=True)
        else:
            FAILURES.append(name)
            print('FAIL', name, repr(out[-600:]), repr(err[-600:]), flush=True)


run('review process failure cannot be accepted', '''
CODEXC_REVIEW_CMD="printf 'BUGS: 0\\n'; exit 42"
review_run task .codingkeeper/review
''', lambda rc, out, err, w: out == 'parse-fail')
run('worker exit status survives DONE marker', '''
CODEXC_HEADLESS_CMD="printf 'TASK_RESULT: DONE\\n'; exit 42"
headless_turn task .codingkeeper/worker
printf '%s' "$?"
''', lambda rc, out, err, w: out == '42')
run('parallel review preserves timeout verdict', '''
CODEXC_REVIEW_TIMEOUT=1
CODEXC_REVIEW_PASS=2
CODEXC_REVIEW_CMD="printf 'BUGS: 0\\n'; sleep 3"
review_batch task .codingkeeper/review >/dev/null
printf '%s' "$?"
''', lambda rc, out, err, w: out == '2')
run('BUGS verdict is exact and bounded', '''
for text in 'prompt says BUGS: 0' 'BUGS: 0garbage' 'BUGS: 999999999999999999999999999999'; do
  printf '%s\\n' "$text" > .codingkeeper/review
  parse_bugs .codingkeeper/review
  printf '\\n'
done
printf 'BUGS: 0002\\n' > .codingkeeper/review
parse_bugs .codingkeeper/review
''', lambda rc, out, err, w: out == 'parse-fail\nparse-fail\nparse-fail\n2')

runner_stubs = '''
pgrep() { return 1; }
register_project() { :; }
notify() { :; }
headless_turn() { printf 'TASK_RESULT: DONE\\n' > "$2"; }
sleep() { touch .codingkeeper/loop.halt; }
'''
run('failed post-review repair gate cannot reach acceptance', runner_stubs + '''
CODEXC_REVIEW_PARALLEL=0
CODEXC_REVIEW_ROUNDS=3
CODEXC_REVIEW_PASS=2
gate_run() { local n; n=$(cat gate-count 2>/dev/null || echo 0); echo $((n+1)) > gate-count; : > "$1"; [ "$n" = 0 ]; }
review_run() { local n; n=$(cat review-count 2>/dev/null || echo 0); echo $((n+1)) > review-count; : > "$2"; if [ "$n" = 0 ]; then printf 1; else printf 0; fi; }
run_runner
''', lambda rc, out, err, w: not (w / '.codingkeeper/journal').exists() and (w / '.codingkeeper/loop.halt').exists())
run('review timeout recovery budget cannot reset each worker turn', runner_stubs + '''
CODEXC_REVIEW_PARALLEL=0
CODEXC_AUTO_RESUME=2
CODEXC_REVIEW_PASS=1
headless_turn() { local n; n=$(cat turn-count 2>/dev/null || echo 0); [ "$n" -lt 5 ] || exit 88; echo $((n+1)) > turn-count; printf 'TASK_RESULT: DONE\\n' > "$2"; }
gate_run() { : > "$1"; return 0; }
review_run() { : > "$2"; printf timeout; }
sleep() { :; }
run_runner
''', lambda rc, out, err, w: rc == 0 and (w / 'turn-count').read_text().strip() == '3')
run('existing non-executable gate must not silently skip', '''
printf '#!/bin/bash\\nexit 17\\n' > .codingkeeper/gate.sh
chmod 600 .codingkeeper/gate.sh
gate_run .codingkeeper/out
printf '%s' "$?"
''', lambda rc, out, err, w: out == '17')

run('runner lock elects one owner under simultaneous starts', """
for n in 1 2 3 4 5 6 7 8; do
  /bin/bash -c '. "$1"; runner_lock_acquire && { printf "WON\\n"; sleep 2; }' audit """ + shlex.quote(str(ROOT / 'ck-common.sh')) + """ &
done
wait
""", lambda rc, out, err, w: out.count('WON') == 1)
run('cleanup cannot delete another ownership token', """
runner_lock_acquire || exit 2
CK_LOCK_TOKEN=incorrect
loop_cleanup
[ -s .codingkeeper/loop.pid ] && [ -s .codingkeeper/runner.owner ]
""", lambda rc, out, err, w: rc == 0)
run('deleting legacy pid cannot admit a second runner', """
runner_lock_acquire || exit 2
rm .codingkeeper/loop.pid
runner_lock_acquire >/dev/null 2>&1
[ "$?" -ne 0 ]
""", lambda rc, out, err, w: rc == 0 and (w / '.codingkeeper/runner.owner').exists())
run('queue replacement ignores planted fixed-temp symlink and preserves mode', """
printf 'private-data' > sentinel
ln -s "$PWD/sentinel" .codingkeeper/queue.md.codingkeeper-tmp
chmod 600 .codingkeeper/queue.md
queue_mark_done .codingkeeper/queue.md dGFzaw==
""", lambda rc, out, err, w: out.strip() == 'marked' and (w / 'sentinel').read_text() == 'private-data'
      and (w / '.codingkeeper/queue.md').stat().st_mode & 0o777 == 0o600)
run('status writers have private unique temporary files', """
printf 'private-data' > sentinel
ln -s "$PWD/sentinel" .codingkeeper/status.json.codingkeeper-tmp
for n in 1 2 3 4 5 6 7 8; do status_write task codex 1 42 & done
wait
""", lambda rc, out, err, w: not err and (w / 'sentinel').read_text() == 'private-data'
      and (w / '.codingkeeper/status.json').stat().st_mode & 0o777 == 0o600)
run('migration preserves live ownership and authoritative new queue', """
runner_lock_acquire || exit 2
mkdir .codexc
printf '99\\n' > .codexc/loop.pid
printf '## ready\\n- [ ] obsolete\\n' > .codexc/queue.md
migrate_state_dir
[ "$(cat .codingkeeper/loop.pid)" = "$$" ]
""", lambda rc, out, err, w: rc == 0 and 'task' in (w / '.codingkeeper/queue.md').read_text())

run('status counts ready section and deduplicates symlink aliases', """
mkdir registry
ln -s "$PWD" alias
printf '%s\\n%s\\n' "$PWD" "$PWD/alias" > registry/projects
printf '## ready\\n- [ ] pending\\n- [x] accepted\\n## review-needed\\n- [ ] proposal\\n' > .codingkeeper/queue.md
# Redirect only the registry argument, keeping the product reader unchanged.
cmd_status() { """ + library()[library().index('    python3 - "$HOME/.codingkeeper/projects"'):library().rindex('\n}')].replace('"$HOME/.codingkeeper/projects"', '"$PWD/registry/projects"') + """
}
cmd_status
""" if '    python3 - "$HOME/.codingkeeper/projects"' in library() else 'exit 2',
    lambda rc, out, err, w: rc == 0 and out.count('1/1') == 1 and '2/1' not in out)

run('manual halt changes within one second remain detectable', """
touch .codingkeeper/loop.halt
before=$(halt_signature)
python3 - <<'PYTOUCH'
import os
p = '.codingkeeper/loop.halt'
s = os.stat(p)
os.utime(p, ns=(s.st_atime_ns, s.st_mtime_ns + 1))
PYTOUCH
after=$(halt_signature)
[ "$before" != "$after" ]
""", lambda rc, out, err, w: rc == 0)
run('dangling gate symlink must fail closed', """
ln -s missing-gate .codingkeeper/gate.sh
gate_run .codingkeeper/out
[ "$?" -ne 0 ]
""", lambda rc, out, err, w: rc == 0)
run('parallel review respects the total review limit', runner_stubs + """
CODEXC_REVIEW_PARALLEL=1
CODEXC_REVIEW_PASS=2
CODEXC_REVIEW_ROUNDS=1
gate_run() { : > "$1"; return 0; }
review_batch() { touch reviewer-was-called; return 0; }
run_runner
""", lambda rc, out, err, w: not (w / 'reviewer-was-called').exists()
      and not (w / '.codingkeeper/journal').exists() and (w / '.codingkeeper/loop.halt').exists())
run('failed repair worker cannot continue into clean reviews', runner_stubs + """
CODEXC_REVIEW_PARALLEL=0
CODEXC_REVIEW_PASS=2
CODEXC_REVIEW_ROUNDS=3
headless_turn() { local n; n=$(cat worker-count 2>/dev/null || echo 0); echo $((n+1)) > worker-count; printf 'TASK_RESULT: DONE\\n' > "$2"; [ "$n" = 0 ]; }
gate_run() { : > "$1"; return 0; }
review_run() { local n; n=$(cat review-count 2>/dev/null || echo 0); echo $((n+1)) > review-count; : > "$2"; if [ "$n" = 0 ]; then printf 1; else printf 0; fi; }
run_runner
""", lambda rc, out, err, w: not (w / '.codingkeeper/journal').exists()
      and (w / '.codingkeeper/loop.halt').exists())

run('active legacy runner blocks migration and a second lane', """
mkdir .codexc
printf '%s\\n' "$$" > .codexc/loop.pid
printf '## ready\\n- [ ] legacy-task\\n' > .codexc/queue.md
runner_lock_acquire >/dev/null 2>&1
[ "$?" -ne 0 ] && [ ! -e .codingkeeper/runner.owner ] && [ -e .codexc/queue.md ]
""", lambda rc, out, err, w: rc == 0)

if FAILURES:
    print(f'ACCEPTANCE AUDIT FAILED ({len(FAILURES)})')
    raise SystemExit(1)
print('ACCEPTANCE AUDIT PASS')
