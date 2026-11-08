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


if __name__ == '__main__':
    unittest.main()
