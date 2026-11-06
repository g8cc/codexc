#!/bin/bash
# Controller gate: fixed full suite, independent of queue counts. Offline models only.
set -eu
cd "$(dirname "$0")/.."
export RUN_REAL_AI=0
exec python3 - <<'PYGATE'
import os
from pathlib import Path
import sys
folders = [Path('tests') / ('phase' + str(i)) for i in range(1, 5)]
folders += [Path('tests') / name for name in ('functional', 'perf', 'quality', 'v2')]
files = sorted({str(p) for folder in folders if folder.is_dir() for p in folder.rglob('*')
                if p.is_file() and p.name.endswith(('.test.js', '.test.mjs'))})
if not files:
    sys.exit('[gate] no test files; refusing empty success')
print('[gate] all phases + functional/perf/quality/v2; real AI disabled; files=' + str(len(files)), flush=True)
os.execvp('node', ['node', '--test', *files])
PYGATE
