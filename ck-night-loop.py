#!/usr/bin/env python3
"""Conservative idle takeover for owned interactive tmux panes; no model calls."""
import argparse
import datetime as dt
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ck_window', ROOT / 'ck-window.py')
window_policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window_policy)


def empty_composer(screen, cursor_y, tool):
    """Unknown layouts, dialogs, drafts and busy screens never authorize a feed."""
    lines = screen.splitlines()
    if not 0 <= cursor_y < len(lines) or 'to interrupt' in screen.lower():
        return False
    line = lines[cursor_y].strip()
    if tool in ('codex', 'claude'):
        marker = '›' if tool == 'codex' else '❯'
        # A single composer row bounded by separators; wrapped drafts are refused.
        if line != marker or cursor_y == 0 or cursor_y + 1 >= len(lines):
            return False
        border = lambda text: bool(re.fullmatch(r'[─━╌┄]+', text.strip())) and len(text.strip()) >= 3
        return border(lines[cursor_y - 1]) and border(lines[cursor_y + 1])
    if tool == 'pi':
        # Pi's default editor is a blank row between two horizontal borders.
        if line or cursor_y == 0 or cursor_y + 1 >= len(lines):
            return False
        return all(re.fullmatch(r'[─━]+', row.strip()) and len(row.strip()) >= 3
                   for row in (lines[cursor_y - 1], lines[cursor_y + 1]))
    # OpenCode/custom themes need a proven composer adapter before takeover.
    return False


class IdleClock:
    def __init__(self, seconds):
        self.seconds = seconds
        self.since = None
        self.previous = None

    def ready(self, now, eligible, fingerprint):
        if not eligible:
            self.since = None
        elif self.since is None or fingerprint != self.previous:
            self.since = now
        self.previous = fingerprint
        return self.since is not None and now - self.since >= self.seconds


def tmux(*args):
    return subprocess.check_output(['tmux', *args], text=True, timeout=5).rstrip('\n')


def owned(pane, owner, project, tool):
    try:
        os.kill(owner, 0)
        values = tmux('display-message', '-p', '-t', pane,
                      '#{pane_id}\t#{@codexc_owner}\t#{@codexc_project}\t#{@codexc_tool}\t#{pane_dead}')
        return values.split('\t') == [pane, str(owner), project, tool, '0']
    except (OSError, subprocess.SubprocessError):
        return False


def snapshot(pane):
    cursor = tmux('display-message', '-p', '-t', pane, '#{cursor_y}')
    screen = tmux('capture-pane', '-p', '-t', pane)
    # Re-read cursor to refuse captures taken across a render/layout change.
    if cursor != tmux('display-message', '-p', '-t', pane, '#{cursor_y}'):
        raise ValueError('cursor changed during capture')
    return screen, int(cursor)


def project_ready(project):
    state = Path(project) / '.codingkeeper'
    if (state / 'loop.halt').exists():
        return False
    try:
        fd = os.open(state / 'gate.sh', os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return False
            raw = source.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            return False
        gate = raw.decode('utf-8')
        if re.search(r'^# CK_GATE_PLACEHOLDER=1$|^echo "\(gate placeholder[ :—]', gate, re.M):
            return False
        subprocess.run(['git', '-C', project, 'rev-parse', '--is-inside-work-tree'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return False
    return True


def run(pane, owner, tool, seconds=600, window='23:00-09:00', timezone='Asia/Singapore'):
    project = os.path.realpath(os.getcwd())
    clock = IdleClock(seconds)
    child = None
    def stop(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    try:
        while owned(pane, owner, project, tool):
            allowed = window_policy.evaluate(window, timezone)['allowed']
            try:
                screen, cursor = snapshot(pane)
                fingerprint = hashlib.sha256((str(cursor) + screen).encode()).digest()
                eligible = allowed and project_ready(project) and empty_composer(screen, cursor, tool)
                ready = clock.ready(time.monotonic(), eligible, fingerprint)
            except (OSError, ValueError, subprocess.SubprocessError):
                clock.ready(time.monotonic(), False, None)
                ready = False
            if ready:
                # Validate ownership, draft and gate again immediately before handing off.
                if (owned(pane, owner, project, tool) and project_ready(project)
                        and snapshot(pane) == (screen, cursor)
                        and window_policy.evaluate(window, timezone)['allowed']):
                    print(f'{dt.datetime.now().isoformat()} night-loop: idle takeover {tool} {pane}', flush=True)
                    release = subprocess.run([sys.executable, str(ROOT / 'ck-interaction.py'), 'release-owner', str(owner)],
                                             capture_output=True, timeout=10)
                    if release.returncode != 0:
                        clock.ready(time.monotonic(), False, None)
                        continue
                    env = dict(os.environ, CODEXC_TOOL=tool, CODEXC_REQUIRE_GATE='1')
                    child = subprocess.Popen([str(ROOT / 'codexc-loop'), 'run', pane], env=env)
                    while child.poll() is None and owned(pane, owner, project, tool):
                        time.sleep(2)
                    return  # One takeover per interactive session; never restart a parked loop.
                clock.ready(time.monotonic(), False, None)
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pane')
    parser.add_argument('owner', type=int)
    parser.add_argument('tool', choices=('codex', 'claude', 'pi', 'opencode'))
    args = parser.parse_args()
    raw = os.environ.get('CODEXC_NIGHT_IDLE', '600')
    if not raw.isascii() or not raw.isdecimal() or not 1 <= int(raw) <= 86400 or args.owner <= 1:
        parser.error('CODEXC_NIGHT_IDLE must be 1..86400 seconds and owner must be a live PID')
    run(args.pane, args.owner, args.tool, int(raw),
        os.environ.get('CODEXC_NIGHT_WINDOW', '23:00-09:00'),
        os.environ.get('CODEXC_NIGHT_TZ', 'Asia/Singapore'))


if __name__ == '__main__':
    main()
