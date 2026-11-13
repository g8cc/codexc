#!/usr/bin/env python3
"""Exercise deployment with fake launchctl; never changes live launchd jobs."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LABELS = ('com.codingkeeper.watchdog', 'com.codexc.daily', 'com.codingkeeper.watchdog-alive')


class WatchdogInstallAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-install-watchdog-', dir='/private/tmp')
        self.world = Path(self.tmp.name)
        self.home = self.world / 'home with spaces'
        self.home.mkdir()
        (self.home / 'Library/LaunchAgents').mkdir(parents=True)
        self.bin = self.world / 'bin'
        self.bin.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': str(self.bin) + ':' + os.environ['PATH'],
                    'FAKE_JOBS': str(self.world / 'jobs.json'), 'LAUNCH_LOG': str(self.world / 'launch.log')}
        (self.world / 'jobs.json').write_text('{}')
        self.script('sleep', '#!/bin/bash\nexit 0\n')
        self.script('ps', '#!/bin/bash\necho "fake __locked-run"\n')
        self.script('pkill', '#!/bin/bash\nexit 0\n')
        self.script('launchctl', '#!' + sys.executable + '\n' + r'''
import json, os, plistlib, sys
from pathlib import Path
path = Path(os.environ['FAKE_JOBS'])
jobs = json.loads(path.read_text())
command, *args = sys.argv[1:]
with open(os.environ['LAUNCH_LOG'], 'a') as out: out.write(' '.join(sys.argv[1:]) + '\n')
label = args[0].split('/')[-1] if args else ''
if command == 'print':
    if label not in jobs: sys.exit(113)
    value = jobs[label]
    print('program = ' + value['ProgramArguments'][0])
    print('arguments = {')
    for arg in value['ProgramArguments']: print('    ' + arg)
    print('}')
elif command == 'bootout':
    if os.environ.get('FAIL_BOOTOUT') == '1': sys.exit(5)
    jobs.pop(label, None)
elif command == 'bootstrap':
    with open(args[1], 'rb') as source: value = plistlib.load(source)
    label = value['Label']
    if label in jobs: sys.exit(5)
    if os.environ.get('STALE_BOOTSTRAP') == label:
        value['ProgramArguments'] = ['/Users/old/Documents/stale-script', 'run']
    jobs[label] = value
else:
    sys.exit('unexpected launchctl command: ' + command)
path.write_text(json.dumps(jobs))
''')

    def script(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_installer(self):
        return subprocess.run(['/bin/bash', str(ROOT / 'packaging/install-watchdog.sh')],
                              env=self.env, text=True, capture_output=True, timeout=20)

    def test_installs_and_verifies_all_three_jobs_for_the_current_home(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        jobs = json.loads((self.world / 'jobs.json').read_text())
        self.assertEqual(set(jobs), set(LABELS))
        for label in LABELS:
            args = jobs[label]['ProgramArguments']
            self.assertTrue(any(str(self.home / '.codingkeeper/bin') in arg for arg in args), args)
            self.assertNotIn('/Documents/', ' '.join(args))
        # A copied daily script must be independently usable, including helpers.
        result = subprocess.run([str(self.home / '.codingkeeper/bin/codexc-daily'), '--help'],
                                env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('cannot source', result.stderr)

    def test_existing_job_that_cannot_be_unloaded_is_an_explicit_failure(self):
        (self.world / 'jobs.json').write_text(json.dumps({LABELS[0]: {'ProgramArguments': ['/old/Documents/script']}}))
        self.env['FAIL_BOOTOUT'] = '1'
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('bootout', result.stdout + result.stderr)
        self.assertNotIn('已由 launchd 托管', result.stdout)

    def test_stale_loaded_arguments_cannot_be_mistaken_for_success(self):
        for label in LABELS:
            with self.subTest(label=label):
                (self.world / 'jobs.json').write_text('{}')
                self.env['STALE_BOOTSTRAP'] = label
                result = self.run_installer()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(label, result.stdout + result.stderr)
                self.assertNotIn('已由 launchd 托管', result.stdout)


if __name__ == '__main__':
    unittest.main()
