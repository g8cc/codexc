#!/usr/bin/env python3
"""Pure daily availability policy. No network, state writes, or model calls.

A configured window is [start, end) in CODEXC_ACTIVE_TZ (Asia/Shanghai by
 default). A missing/empty window leaves other tools unrestricted. Invalid
 configuration closes the gate. --now is an explicit CLI test clock only.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def evaluate(window, timezone='Asia/Shanghai', now=None):
    def decision(allowed, deadline=0, next_open=0, reason='allowed'):
        return dict(allowed=allowed, deadline=deadline, next_open=next_open, reason=reason)

    if window is None or window == '':
        return decision(True, reason='disabled')
    if not isinstance(window, str):
        return decision(False, reason='invalid_window')
    match = re.fullmatch(r'([0-9]{2}):([0-9]{2})-([0-9]{2}):([0-9]{2})', window)
    if not match:
        return decision(False, reason='invalid_window')
    sh, sm, eh, em = map(int, match.groups())
    if sh > 23 or eh > 23 or sm > 59 or em > 59 or (sh, sm) == (eh, em):
        return decision(False, reason='invalid_window')
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return decision(False, reason='invalid_timezone')
    try:
        instant = time.time() if now is None else float(now)
        if not math.isfinite(instant):
            raise ValueError('non-finite clock')
        local = dt.datetime.fromtimestamp(instant, zone)
    except (ValueError, TypeError, OverflowError, OSError):
        return decision(False, reason='invalid_clock')
    overnight = (sh, sm) > (eh, em)
    intervals = []
    rechecks = []
    try:
        for delta in range(-2, 10):
            start_date = local.date() + dt.timedelta(days=delta)
            end_date = start_date + dt.timedelta(days=1 if overnight else 0)
            start = dt.datetime.combine(start_date, dt.time(sh, sm), zone)
            end = dt.datetime.combine(end_date, dt.time(eh, em), zone)
            intervals.append((int(start.timestamp()), int(end.timestamp())))
            rechecks.append(int(start.timestamp()))
            if start_date.weekday() >= 5:
                start = dt.datetime.combine(start_date, dt.time(), zone)
                end = dt.datetime.combine(start_date + dt.timedelta(days=1), dt.time(), zone)
                intervals.append((int(start.timestamp()), int(end.timestamp())))
                rechecks.append(int(start.timestamp()))
    except (ValueError, OverflowError, OSError):
        return decision(False, reason='invalid_clock')
    # Merge adjoining weekend/daily windows. Fri night continues until Mon
    # morning, and a Sunday worker receives a real Mon cutoff, not deadline=0.
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    next_open = min((start for start in rechecks if start > instant), default=0)
    for start, end in merged:
        if start <= instant < end:
            return decision(True, end, next_open, 'weekend' if local.weekday() >= 5 else 'allowed')
    return decision(False, next_open=next_open, reason='outside_window')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--now', help='explicit epoch seconds for deterministic tests')
    parser.add_argument('--format', choices=('json', 'tsv'), default='json')
    args = parser.parse_args()
    result = evaluate(os.environ.get('CODEXC_ACTIVE_WINDOW'),
                      os.environ.get('CODEXC_ACTIVE_TZ', 'Asia/Shanghai'), args.now)
    if args.format == 'tsv':
        print(f"{int(result['allowed'])}\t{result['deadline']}\t{result['next_open']}\t{result['reason']}")
    else:
        print(json.dumps(result, separators=(',', ':')))
    return 2 if result['reason'].startswith('invalid_') else 0


if __name__ == '__main__':
    raise SystemExit(main())
