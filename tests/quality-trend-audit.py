#!/usr/bin/env python3
"""质量退化遥测的回归: journal 解析 / 逐日聚合 / 阈值告警。"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "ck-quality-trend", REPO / "ck-quality-trend.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_journal(rows):
    tmp = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False)
    for r in rows:
        tmp.write(r + '\n')
    tmp.close()
    return tmp.name


class QualityTrendAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def tearDown(self):
        import os
        for attr in ('_path',):
            p = getattr(self, attr, None)
            if p and os.path.exists(p):
                os.unlink(p)

    def journal(self, rows):
        self._path = write_journal(rows)
        return self.mod.parse(self._path)

    def test_parse_extracts_rounds_and_retries(self):
        days = self.journal([
            '2026-11-08 09:56:33 | (idle 持续改进) | accepted after 2 review round(s), gate retries 1 | receipt=a',
            '2026-11-08 10:11:46 | 队列任务 | accepted after 4 review round(s), gate retries 0 | receipt=b',
            '2026-11-08 10:52:04 | 其他 | parked: review rounds exhausted',
            'noise line without accepted marker',
        ])
        self.assertEqual(days['2026-11-08']['accepted'], 2)
        self.assertEqual(days['2026-11-08']['rounds'], 6)
        self.assertEqual(days['2026-11-08']['max_rounds'], 4)
        self.assertEqual(days['2026-11-08']['retries'], 1)

    def test_clean_today_is_ok(self):
        days = self.journal([
            '2026-11-07 10:00:00 | x | accepted after 2 review round(s), gate retries 0 | receipt=a',
            '2026-11-08 10:00:00 | x | accepted after 2 review round(s), gate retries 0 | receipt=b',
        ])
        result = self.mod.trend(days)
        self.assertEqual(result['verdict'], 'ok')
        self.assertEqual(result['alerts'], [])

    def test_high_average_rounds_alerts(self):
        days = self.journal([
            f'2026-11-0{d} 10:00:00 | x | accepted after 4 review round(s), gate retries 0 | receipt={d}'
            for d in range(5, 8)
        ] + [
            '2026-11-08 10:00:00 | x | accepted after 4 review round(s), gate retries 0 | receipt=t1',
            '2026-11-08 11:00:00 | x | accepted after 4 review round(s), gate retries 0 | receipt=t2',
        ])
        result = self.mod.trend(days, today='2026-11-08')
        self.assertEqual(result['verdict'], 'alert')
        self.assertTrue(any('3.5' in a for a in result['alerts']))

    def test_rising_trend_alerts_even_below_absolute_cap(self):
        rows = [f'2026-11-0{d} 10:00:00 | x | accepted after 2 review round(s), gate retries 0 | receipt={d}{i}'
                for d in range(5, 8) for i in range(2)]
        rows += [
            '2026-11-08 10:00:00 | x | accepted after 3 review round(s), gate retries 0 | receipt=t1',
            '2026-11-08 11:00:00 | x | accepted after 3 review round(s), gate retries 0 | receipt=t2',
            '2026-11-08 12:00:00 | x | accepted after 4 review round(s), gate retries 0 | receipt=t3',
        ]
        result = self.mod.trend(self.journal(rows), today='2026-11-08')
        self.assertEqual(result['verdict'], 'alert')
        self.assertTrue(any('高于前' in a for a in result['alerts']),
                        'trend alert must fire: today 3.33 > prev 2.0 + 1.0')
        self.assertFalse(any('3.5' in a for a in result['alerts']),
                         '3.33 is below the absolute cap; this isolates the trend alert')

    def test_gate_retry_rate_alerts(self):
        rows = [f'2026-11-0{d} 10:00:00 | x | accepted after 2 review round(s), gate retries 0 | receipt={d}{i}'
                for d in range(5, 8) for i in range(2)]
        rows += [
            '2026-11-08 10:00:00 | x | accepted after 2 review round(s), gate retries 1 | receipt=t1',
            '2026-11-08 11:00:00 | x | accepted after 2 review round(s), gate retries 1 | receipt=t2',
        ]
        result = self.mod.trend(self.journal(rows), today='2026-11-08')
        self.assertEqual(result['verdict'], 'alert')
        self.assertTrue(any('gate 重试率' in a for a in result['alerts']))

    def test_empty_journal_is_ok(self):
        result = self.mod.trend(self.journal(['nothing here']))
        self.assertEqual(result['verdict'], 'ok')

    def parks(self, rows):
        self._parks_path = write_journal(rows)
        return self.mod.parse_parks(self._parks_path)

    def test_park_lines_count_toward_instability_alert(self):
        days = self.journal([
            '2026-11-08 03:00:00 | x | accepted after 2 review round(s), gate retries 0 | receipt=a',
        ])
        parks = self.parks([
            '2026-11-08 01:00:00 | (park) | review rounds exhausted',
            '2026-11-08 02:00:00 | (park) | review output unparseable',
        ])
        result = self.mod.trend(days, parks, today='2026-11-08')
        self.assertEqual(result['verdict'], 'alert')
        self.assertTrue(any('park 2 次' in a for a in result['alerts']))
        self.assertEqual(result['today']['accepted'], 1)

    def test_single_park_is_not_an_alert(self):
        days = self.journal([
            '2026-11-08 03:00:00 | x | accepted after 2 review round(s), gate retries 0 | receipt=a',
        ])
        parks = self.parks(['2026-11-08 01:00:00 | (park) | review rounds exhausted'])
        result = self.mod.trend(days, parks, today='2026-11-08')
        self.assertEqual(result['verdict'], 'ok')

    def test_alert_exit_code_is_not_treated_as_failure(self):
        # 回归: 钩子曾用 '|| continue' 把 verdict=alert (rc=1) 当失败吞掉,
        # 导致恰好处于告警状态的炉子看不到遥测行
        watch = (REPO / 'burn-watch.sh').read_text(encoding='utf-8')
        self.assertNotIn('.py" "$qjournal" "$HOME/Documents/work/code/AI/AIworkspace/$qproj/.codingkeeper/parks.log" 2>/dev/null)" || continue',
                         watch)
        self.assertIn('[ "$qtrc" -ge 2 ] && continue', watch)

    def test_park_only_day_appears_in_tail_and_counts(self):
        parks = self.parks([
            '2026-11-07 01:00:00 | (park) | review rounds exhausted',
            '2026-11-08 01:00:00 | (park) | review output unparseable',
            '2026-11-08 02:00:00 | (park) | review output unparseable',
        ])
        result = self.mod.trend({}, parks, today='2026-11-08')
        self.assertEqual(result['verdict'], 'alert')


if __name__ == '__main__':
    unittest.main()
