#!/bin/bash
# install-watchdog.sh — 看门狗 launchd 部署/重装 (交接手册 §7.8 三步的固化 + 运行位副本)。
#
# 前置 (一次性, 须人工): System Settings → Privacy & Security → Full Disk Access
# 添加 /bin/bash。launchd 拉起的进程没有 ~/Documents 的 TCC 授权 (2026-11-09 探针
# 实证: 脚本与炉子状态文件一律 DENIED), 未授权时实例能起但巡逻必然被内核拒绝。
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
bin_dir="$HOME/.codingkeeper/bin"
runtime="$bin_dir/burn-watch.sh"

mkdir -p "$bin_dir"
cp "$repo/burn-watch.sh" "$runtime"                                  # 运行位副本
chmod +x "$runtime"
ln -sfn "$repo/burn-watch.sh" "$HOME/.codingkeeper/burn-watch.sh"    # 手动入口仍指仓库真源

pkill -f 'burn-watch.sh __locked-run' 2>/dev/null || true            # 让位给 launchd 实例
sleep 1

bootout gui/$(id -u)/com.codingkeeper.watchdog 2>/dev/null || true
cp "$here/com.codingkeeper.watchdog.plist" "$HOME/Library/LaunchAgents/"
bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.codingkeeper.watchdog.plist"

# 同病同修: com.codexc.daily (每日 10:00) 也曾直指 Documents 下脚本, 从未跑成过
cp "$repo/codexc-daily" "$bin_dir/codexc-daily" && chmod +x "$bin_dir/codexc-daily"
bootout gui/$(id -u)/com.codexc.daily 2>/dev/null || true
cp "$here/com.codexc.daily.plist" "$HOME/Library/LaunchAgents/"
bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.codexc.daily.plist"

# 心跳守夜员: 只读 ~/.codingkeeper, 无 FDA 也能被 launchd 托管 — 主看门狗死亡的兜底监控
cp "$repo/ck-watchdog-alive.sh" "$bin_dir/ck-watchdog-alive.sh" && chmod +x "$bin_dir/ck-watchdog-alive.sh"
bootout gui/$(id -u)/com.codingkeeper.watchdog-alive 2>/dev/null || true
cp "$here/com.codingkeeper.watchdog-alive.plist" "$HOME/Library/LaunchAgents/"
bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.codingkeeper.watchdog-alive.plist"

sleep 3
if LC_ALL=C ps ax -o command | LC_ALL=C grep -q '__locked-run'; then
    echo "✓ 看门狗已由 launchd 托管 (心跳 $HOME/.codingkeeper/watchdog.heartbeat, 15 分钟不更新即异常)"
    echo "✓ com.codexc.daily 已注册 (每日 10:00 触发, 日志 $HOME/.codex/codexc-daily.log)"
else
    echo "✗ launchd 实例未存活 — 查 $HOME/.codingkeeper/burn-watch.log"
    echo "  十有八九是 /bin/bash 未获完全磁盘访问 (TCC deny 记录在内核日志: System Policy: bash deny file-read-data)"
    exit 1
fi
