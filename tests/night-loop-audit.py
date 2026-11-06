#!/usr/bin/env python3
"""Night takeover policy and lifecycle tests; no provider calls or live panes."""
import datetime as dt
import importlib.util
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('night', ROOT / 'ck-night-loop.py')
night = importlib.util.module_from_spec(spec)
spec.loader.exec_module(night)


class NightTests(unittest.TestCase):
    def test_ten_minutes_after_window_opens(self):
        clock = night.IdleClock(600)
        self.assertFalse(clock.ready(0, False, 'empty'))
        self.assertFalse(clock.ready(500, True, 'empty'))
        self.assertFalse(clock.ready(1099, True, 'empty'))
        self.assertTrue(clock.ready(1100, True, 'empty'))

    def test_input_render_or_busy_resets_timer(self):
        for reset in ('draft', 'new answer', 'cursor moved'):
            clock = night.IdleClock(600)
            clock.ready(0, True, 'empty')
            self.assertFalse(clock.ready(599, True, reset))
            self.assertFalse(clock.ready(600, True, reset))
            self.assertTrue(clock.ready(1199, True, reset))
        clock.ready(1200, False, 'busy')
        self.assertFalse(clock.ready(1801, True, 'empty'))

    def test_midnight_and_end_boundary(self):
        for hour, minute, allowed in ((23, 59, False), (0, 0, True), (7, 59, True), (8, 0, False)):
            instant = dt.datetime(2026, 11, 7, hour, minute, tzinfo=ZoneInfo('Asia/Singapore')).timestamp()
            result = night.window_policy.evaluate('00:00-08:00', 'Asia/Singapore', instant)
            self.assertEqual(result['allowed'], allowed)
        self.assertFalse(night.window_policy.evaluate('broken', 'Asia/Singapore')['allowed'])
        self.assertFalse(night.window_policy.evaluate('00:00-08:00', 'bad-zone')['allowed'])

    def test_composer_layouts_and_drafts(self):
        for tool, marker in (('codex', '›'), ('claude', '❯'), ('pi', '')):
            screen = f'answer\n──────────\n{marker} \n──────────\nstatus'
            self.assertTrue(night.empty_composer(screen, 2, tool), tool)
            self.assertFalse(night.empty_composer(screen.replace(marker + ' \n', marker + ' draft\n'), 2, tool))
            self.assertFalse(night.empty_composer(screen + '\nesc to interrupt', 2, tool))
            self.assertFalse(night.empty_composer(screen, 9, tool))
            self.assertFalse(night.empty_composer(screen.replace('answer', 'ctrl+c to interrupt'), 2, tool))
            multiline = f'answer\n──────────\n{marker} draft\n\n──────────'
            self.assertFalse(night.empty_composer(multiline, 3, tool))
        self.assertFalse(night.empty_composer('choose approval\n❯ allow', 1, 'claude'))
        self.assertFalse(night.empty_composer('›', 0, 'codex'))
        self.assertFalse(night.empty_composer('ctrl+p commands', 0, 'opencode'))

    def test_text_rows_are_not_composer_borders(self):
        for tool, marker in (('codex', '›'), ('claude', '❯'), ('pi', '')):
            self.assertFalse(night.empty_composer(f'sssss\n{marker}\nsssss', 1, tool))
            self.assertTrue(night.empty_composer(f'  ─────  \n{marker}\n  ─────  ', 1, tool))

    def test_nonregular_or_oversized_gate_never_blocks_takeover_monitor(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)/'.codingkeeper'
            state.mkdir()
            gate = state/'gate.sh'
            code = ('import importlib.util; s=importlib.util.spec_from_file_location("night",'
                    + repr(str(ROOT/'ck-night-loop.py')) + '); m=importlib.util.module_from_spec(s); '
                    's.loader.exec_module(m); print(m.project_ready(' + repr(temp) + '))')
            os.mkfifo(gate)
            result = subprocess.run([os.sys.executable, '-c', code], capture_output=True, text=True, timeout=2)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'False')
            gate.unlink()
            gate.write_text('#' * (2*1024*1024+1))
            with patch.object(night.subprocess, 'run'):
                self.assertFalse(night.project_ready(temp))

    def test_gate_and_halt(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / '.codingkeeper'
            state.mkdir()
            with patch.object(night.subprocess, 'run'):
                self.assertFalse(night.project_ready(temp))
                gate = state / 'gate.sh'
                gate.write_text('# CK_GATE_PLACEHOLDER=1\nexit 0\n')
                self.assertFalse(night.project_ready(temp))
                gate.write_text('#!/bin/bash\npytest\n')
                self.assertTrue(night.project_ready(temp))
                (state / 'loop.halt').touch()
                self.assertFalse(night.project_ready(temp))

    def test_ownership_requires_every_field(self):
        with patch.object(night.os, 'kill'), patch.object(night, 'tmux') as tmux:
            tmux.return_value = '%1\t1234\t/project\tcodex\t0'
            self.assertTrue(night.owned('%1', 1234, '/project', 'codex'))
            self.assertFalse(night.owned('%1', 1235, '/project', 'codex'))
            self.assertFalse(night.owned('%1', 1234, '/other', 'codex'))
            self.assertFalse(night.owned('%1', 1234, '/project', 'claude'))
            tmux.return_value = '%1\t1234\t/project\tcodex\t1'
            self.assertFalse(night.owned('%1', 1234, '/project', 'codex'))

    def test_handoff_once_and_force_real_gate(self):
        clock = Mock()
        clock.ready.return_value = True
        child = Mock()
        child.poll.return_value = 0
        with patch.object(night, 'IdleClock', return_value=clock), \
             patch.object(night, 'owned', return_value=True), \
             patch.object(night, 'snapshot', return_value=('empty', 2)), \
             patch.object(night, 'empty_composer', return_value=True), \
             patch.object(night, 'project_ready', return_value=True), \
             patch.object(night.window_policy, 'evaluate', return_value={'allowed': True}), \
             patch.object(night.subprocess, 'Popen', return_value=child) as launch:
            night.run('%1', 1234, 'claude')
            launch.assert_called_once()
            args, kwargs = launch.call_args
            self.assertEqual(args[0][-2:], ['run', '%1'])
            self.assertEqual(kwargs['env']['CODEXC_TOOL'], 'claude')
            self.assertEqual(kwargs['env']['CODEXC_REQUIRE_GATE'], '1')

    def test_recheck_prevents_handoff_after_input(self):
        clock = Mock()
        clock.ready.return_value = True
        with patch.object(night, 'IdleClock', return_value=clock), \
             patch.object(night, 'owned', side_effect=[True, True, False]), \
             patch.object(night, 'snapshot', side_effect=[('empty', 2), ('draft', 2)]), \
             patch.object(night, 'empty_composer', return_value=True), \
             patch.object(night, 'project_ready', return_value=True), \
             patch.object(night.window_policy, 'evaluate', return_value={'allowed': True}), \
             patch.object(night.time, 'sleep'), \
             patch.object(night.subprocess, 'Popen') as launch:
            night.run('%1', 1234, 'codex')
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
