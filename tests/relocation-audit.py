#!/usr/bin/env python3
"""Offline relocation of a generated reviewer, including shell-special paths."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RelocationTests(unittest.TestCase):
    def test_only_root_runtime_state_is_ignored(self):
        with tempfile.TemporaryDirectory(prefix='ck-ignore-', dir='/private/tmp') as tmp:
            world = Path(tmp)
            (world / '.gitignore').write_bytes((ROOT / '.gitignore').read_bytes())
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       HOME=str(world), GIT_DIR=str(world / '.git'), GIT_WORK_TREE=str(world))
            subprocess.run(['git', 'init', '--template=', '-q', str(world)], env=env, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            paths = ['.codingkeeper/status.json', '.codingkeeper/queue.md', '.codingkeeper/runner.owner',
                     'docs/prepared/project/.codingkeeper/review-leaf.sh', 'ck']
            result = subprocess.run(['git', '-C', str(world), 'check-ignore', '--stdin'],
                                    input='\n'.join(paths) + '\n', env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.stdout.splitlines(), paths[:3], result.stderr)

    def test_generated_reviewer_survives_controller_move(self):
        self.check_relocation('old-controller')

    def test_generated_reviewer_quotes_controller_path(self):
        self.check_relocation("old $literal 'controller'")

    def check_relocation(self, source_name):
        with tempfile.TemporaryDirectory(prefix='ck-relocation-', dir='/private/tmp') as tmp:
            world = Path(tmp)
            source = world / source_name
            destination = world / "codingKeeper $literal 'new'"
            source.mkdir()
            for name in ('ck-init-furnace', 'ck-common.sh'):
                shutil.copy2(ROOT / name, source / name)
            reviewer = source / 'codexc-review-leaf'
            reviewer.write_text('import json,os,sys\nprint(json.dumps([os.getcwd(), sys.argv[1:]]))\n')
            reviewer.chmod(0o755)
            home = world / 'home'
            bindir = home / '.codex/bin'
            bindir.mkdir(parents=True)
            project = world / 'project with spaces'
            project.mkdir()
            # Never select a real reviewer from the host/test-harness PATH.
            tools = world / 'bin'
            tools.mkdir()
            (tools / 'python3').symlink_to(sys.executable)
            env = dict(os.environ, HOME=str(home), CODEXC_REGISTER_TEMP='1',
                       PATH=str(tools) + os.pathsep + '/usr/bin:/bin:/usr/sbin:/sbin')
            generated = subprocess.run(['/bin/bash', str(source / 'ck-init-furnace'), str(project), 'true'],
                                       env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            script = project / '.codingkeeper/review-leaf.sh'
            # Direct repository use must work before installation, too.
            initial = subprocess.run(['/bin/bash', str(script), 'before move'],
                                     env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(initial.returncode, 0, initial.stderr)
            source.rename(destination)
            (bindir / 'codexc-review-leaf').symlink_to(destination / 'codexc-review-leaf')
            # launchd need not have ~/.codex/bin in PATH; use its stable location.
            result = subprocess.run(['/bin/bash', str(script), 'arg $literal', "single'quote"],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [str(project), ['arg $literal', "single'quote"]])


if __name__ == '__main__':
    unittest.main(verbosity=2)
