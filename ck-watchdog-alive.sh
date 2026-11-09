#!/bin/bash
# ck-watchdog-alive — 看门狗心跳守夜 (launchd StartInterval 600 托管)。
# 心跳 >15 分钟陈旧 = 主看门狗死亡: ALERTS 留档 + osascript 通知 (每小时去重)。
# 本脚本只读 $HOME/.codingkeeper (Documents 之外), launchd 无 FDA 也能跑 —
# 它是 FDA 授权前的兜底监控, FDA 授权后 KeepAlive 主看门狗由 launchd 直接管。
set -u
hb="$HOME/.codingkeeper/watchdog.heartbeat"
# 心跳缺失 = 看门狗从未巡逻 (launchd bootstrap 失败族: job 被 KeepAlive 三连拒
# 移除后无人值守) — 按无限陈旧处理, fail-alarm 而非 fail-open 静默; 去重保证
# 每小时至多一条, 不会刷屏
last=0
[ -f "$hb" ] && last="$(cat "$hb" 2>/dev/null || echo 0)"
age=$(( $(date +%s) - last ))
[ "$age" -lt 900 ] && exit 0

# 每小时去重: 守夜员每 10 分钟醒一次, 死亡未处理时别把 ALERTS 刷屏
mark="$HOME/.codingkeeper/watchdog-alive.last"
now=$(date +%s)
prev=0; [ -f "$mark" ] && prev="$(cat "$mark" 2>/dev/null || echo 0)"
[ $(( now - prev )) -lt 3600 ] && exit 0
echo "$now" > "$mark"

alert="$HOME/.codingkeeper/burn-ALERTS.txt"
echo "$(date '+%F %T') | watchdog | 心跳陈旧 ${age}s — 主看门狗死亡, 舰队无人值守! 重启: nohup /bin/bash \"$HOME/.codingkeeper/bin/burn-watch.sh\" run >> \"$HOME/.codingkeeper/burn-watch.log\" 2>&1 & (FDA 授权后 launchd KeepAlive 接管)" >> "$alert"
osascript -e 'display notification "看门狗心跳陈旧 — 烧炉舰队已无人值守, 请重启 burn-watch" with title "CodingKeeper"' 2>/dev/null || true
