#!/usr/bin/env python3
"""质量退化遥测: 解析 journal 的 accepted 行, 输出逐日趋势 + 阈值告警。

用法: ck-quality-trend.py <journal-path>
输出: JSON {verdict: ok|alert, alerts: [...], today: {...}, days: {...}}
退出码: alert=1, ok=0 — 看门狗据此 alert()。
"""
import json
import re
import sys
from collections import defaultdict

ROW = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} \| .*?'
    r'accepted after (?P<rounds>\d+) review round\(s\), gate retries (?P<retries>\d+)'
)
PARK = re.compile(r'^(?P<ts>\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} \| \(park\) \| ')


def parse(path):
    days = defaultdict(lambda: {"accepted": 0, "rounds": 0, "max_rounds": 0, "retries": 0})
    try:
        fh = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return days
    with fh:
        for line in fh:
            m = ROW.match(line.strip())
            if not m:
                continue
            d = days[m['ts']]
            d["accepted"] += 1
            rounds = int(m['rounds'])
            d["rounds"] += rounds
            d["max_rounds"] = max(d["max_rounds"], rounds)
            d["retries"] += int(m['retries'])
    return days


def parse_parks(path):
    days = defaultdict(lambda: {"parks": 0})
    try:
        fh = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return days
    with fh:
        for line in fh:
            m = PARK.match(line.strip())
            if m:
                days[m['ts']]["parks"] += 1
    return days


def trend(days, parks=None, today=None, prev_days=3):
    for k, v in (parks or {}).items():
        days.setdefault(k, {"accepted": 0, "rounds": 0, "max_rounds": 0, "retries": 0})
        days[k]["parks"] = v["parks"]
    dates = sorted(days)
    tail = {k: days[k] for k in dates[-prev_days:]}
    if not dates:
        return {"verdict": "ok", "alerts": [], "days": {}}
    today = today or dates[-1]
    t = days.get(today) or {"accepted": 0, "rounds": 0, "retries": 0, "parks": 0}
    alerts = []
    # park 稳定性信号独立于验收: 整天 park 零验收是最差信号, 不能被提前返回挡住
    if t.get("parks", 0) >= 2:
        alerts.append(f"今日 park {t['parks']} 次 — 燃烧不稳定")
    if t.get("accepted", 0) > 0:
        t_avg = t["rounds"] / t["accepted"]
        t_retry = t["retries"] / t["accepted"]
        if t_avg > 3.5:
            alerts.append(f"今日平均审核轮数 {t_avg:.1f} > 3.5")
        prev = [days[k] for k in dates if k < today][-prev_days:]
        p_leaves = sum(x["accepted"] for x in prev)
        if len(prev) >= 2 and p_leaves >= 3:
            p_avg = sum(x["rounds"] for x in prev) / p_leaves
            if t_avg > p_avg + 1.0:
                alerts.append(f"今日平均轮数 {t_avg:.1f} 高于前{len(prev)}日均值 {p_avg:.1f} + 1.0 — 退化信号")
        if t_retry > 0.5:
            alerts.append(f"今日 gate 重试率 {t_retry:.2f}/叶 > 0.5")
    return {
        "verdict": "alert" if alerts else "ok",
        "alerts": alerts,
        "today": {"accepted": t.get("accepted", 0),
                  "avg_rounds": round(t["rounds"] / t["accepted"], 2) if t.get("accepted") else 0,
                  "gate_retry_rate": round(t["retries"] / t["accepted"], 2) if t.get("accepted") else 0,
                  "parks": t.get("parks", 0)},
        "days": tail,
    }


def main():
    parks = parse_parks(sys.argv[2]) if len(sys.argv) > 2 else None
    result = trend(parse(sys.argv[1]), parks)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["verdict"] == "alert" else 0


if __name__ == '__main__':
    sys.exit(main())
