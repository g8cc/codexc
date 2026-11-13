#!/usr/bin/env python3
"""审核类 park 的夜间自愈: park 原因入 halt 文件, 看门狗有界自动复燃。"""
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

# CK_AUDIT_SOURCE: 指向保存的旧源码目录, 用于回归重放 (先红后绿取证)
REPO = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parent.parent))


class ParkReviveAudit(unittest.TestCase):
    def read(self, name):
        return (REPO / name).read_text(encoding='utf-8')

    def test_park_writes_reason_and_preserves_operator_halt(self):
        text = self.read('codexc-headless').rsplit('\ncase "${1:-}" in', 1)[0]
        text = '\n'.join('. ' + shlex.quote(str(REPO / 'ck-common.sh'))
                         if line.startswith('. "$(dirname') else line for line in text.splitlines())
        with tempfile.TemporaryDirectory(prefix='ck-park-', dir='/private/tmp') as tmp:
            state = Path(tmp) / '.codingkeeper'; state.mkdir()
            body = text + '\nnotify() { :; }; log() { :; }; headless_wait_status() { :; }\npark notice "review output unparseable"\n'
            result = subprocess.run(['/bin/bash', '-c', body], cwd=tmp,
                                    env={**os.environ, 'HOME': tmp}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            halt = state / 'loop.halt'
            self.assertEqual(halt.read_text(), 'review output unparseable')
            halt.write_text('operator pause')
            inode = halt.stat().st_ino
            result = subprocess.run(['/bin/bash', '-c', body], cwd=tmp,
                                    env={**os.environ, 'HOME': tmp}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(halt.read_text(), 'operator pause')
            self.assertEqual(halt.stat().st_ino, inode)

    def test_fleet_is_registry_discovered_not_hardcoded(self):
        watch = self.read('burn-watch.sh')
        # 字面逐行消费注册表 (read -r): for $( ) 的词分割+glob 展开会把字面名
        # 含元字符目录的同 pattern 兄弟绕过审查卷进巡逻 (glob 注入)
        self.assertGreaterEqual(watch.count('done 3< <(fleet_furnaces)'), 3,
                                'patrol/telemetry/accounting must consume the registry line-by-line')
        self.assertNotIn('for d in $(fleet_furnaces)', watch,
                         'unquoted command substitution must not iterate the registry')
        self.assertNotIn('for proj in fingerprint sale', watch,
                         'hardcoded furnace lists are unmaintainable at fleet scale')
        self.assertIn('.codingkeeper/projects', watch,
                      'fleet must be driven by the project registry')
        self.assertIn('FLEET_EXCLUDE', watch, 'sandbox workspaces must be excludable')
        for required in ('queue.md', 'gate.sh', 'review-leaf.sh'):
            self.assertIn(required, watch,
                          f'{required} must gate fleet membership (incomplete scaffolds must not burn)')

    def test_no_evidence_change_has_no_destructive_rollback(self):
        headless = self.read('codexc-headless')
        self.assertNotIn('git reset --hard', headless,
                         'missing evidence never authorizes loss of user WIP')
        self.assertIn('idle change missing evidence; work preserved', headless)
        self.assertIn('>> ".codingkeeper/parks.log"', headless,
                      'unaccepted work must be observable outside receipt-only journal')

    def test_evidence_check_rejects_verbatim_template_echo(self):
        headless = self.read('codexc-headless')
        self.assertIn("grep -qvE '证据[:：][[:space:]]*<依据>'", headless,
                      'echoing the discipline template verbatim is not evidence')

    def test_watchdog_auto_revives_review_parks_within_budget(self):
        watch = self.read('burn-watch.sh')
        for needle in ('*"review rounds exhausted"*', '*"review output unparseable"*'):
            self.assertIn(needle, watch, f'sweep must auto-revive {needle}')
        self.assertGreaterEqual(watch.count('if revive_parked "$d"; then'), 2)
        self.assertIn('复燃#$proj#', watch, 'review-park revive must share the 2/day budget')
        self.assertIn('复燃超限(2) — 审核 park 留档待人', watch)

    def test_other_halt_reasons_stay_human_only(self):
        watch = self.read('burn-watch.sh')
        # 提取巡逻 halted 分支 (到循环下一条语句为止, 避免内层 fi 截断)
        start = watch.index('if [ "$halted" = 1 ]; then')
        end = watch.index('# Check each project', start)
        branch = watch[start:end]
        self.assertIn('*"review rounds exhausted"*', branch)
        self.assertIn('*"review output unparseable"*', branch)
        self.assertIn('项目已暂停 — 保留 loop.halt', branch,
                      'manual/other parks must never be auto-revived')
        # 人工 halt 的 alert 必须在 *) 兜底分支里, 且不在自动复燃分支内
        lines = branch.splitlines()
        fallback_line = next(i for i, l in enumerate(lines) if l.strip() == '*)')
        human_alert_line = next(i for i, l in enumerate(lines) if '项目已暂停' in l)
        self.assertGreater(human_alert_line, fallback_line,
                           'the human-only alert must live in the *) fallback branch')
        fallback_body = '\n'.join(lines[fallback_line:])
        self.assertNotIn('rm -f', fallback_body,
                         'the *) fallback must not clear halts')

    def test_quality_trend_alert_points_at_the_real_log(self):
        # 独立审查: quality-trend 行住在 codexc-watch.log (~/.codingkeeper/
        # burn-watch.log 是 launchd stdout, 不含该行) — 告警指引不得指向旧文件
        watch = self.read('burn-watch.sh')
        self.assertIn('详情看 codexc-watch.log', watch)
        self.assertNotIn('burn-watch.log 的 quality-trend', watch,
                         '按告警指引找不到故障 = 不可定位')

    def test_fleet_furnaces_discovery_semantics(self):
        """注册表 + 三件套 + 排除表: 四类项目的判定 (进程级, 临时 world)。"""
        with tempfile.TemporaryDirectory(prefix='ck-fleet-', dir='/private/tmp') as tmp:
            home = Path(tmp) / 'home'
            (home / '.codingkeeper').mkdir(parents=True)
            reg = home / '.codingkeeper' / 'projects'
            ws = Path(tmp) / 'ws'
            reg.write_text('')
            for name, files in (
                    ('good', ['queue.md', 'gate.sh', 'review-leaf.sh']),
                    ('incomplete', ['queue.md']),                       # 缺 gate/review
                    ('excluded', ['queue.md', 'gate.sh', 'review-leaf.sh']),
            ):
                d = ws / name / '.codingkeeper'
                d.mkdir(parents=True)
                for f in files:
                    (d / f).write_text('#!/bin/bash\n')
                with open(reg, 'a') as fh:
                    fh.write(f'{ws / name}\n')
            (ws / 'ghost' / '.codingkeeper').mkdir(parents=True)   # 未登记 → 不烧

            src = self.read('burn-watch.sh')
            start = src.index('fleet_furnaces() {')
            end = src.index('\n}', start)
            func = src[start:end + 2]
            out = subprocess.run(
                ['bash', '-c', f'FLEET_EXCLUDE="excluded"\n{func}\nfleet_furnaces'],
                env={**os.environ, 'HOME': str(home)},
                capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.split(), [str(ws / 'good')],
                             f'只应发现齐全且登记且未排除的炉子: {out.stdout} {out.stderr}')


if __name__ == '__main__':
    unittest.main()
