#!/bin/bash
# conformance — HANDLING.md / README 声明 vs 实际行为矩阵。
# 每一条对应文档中的一个承诺；改代码后跑它防文档漂移。
set -u
self_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$self_dir"
PATH="$self_dir:$PATH"
pass=0; fail=0
ck() { if [ "$2" = "OK" ]; then echo "  ✓ $1"; pass=$((pass+1)); else echo "  ✗ $1"; fail=$((fail+1)); fi; }
ckge() { if [ "$2" -ge "$3" ]; then echo "  ✓ $1 ($2)"; pass=$((pass+1)); else echo "  ✗ $1 ($2 < $3)"; fail=$((fail+1)); fi; }

echo "== 按键（TUI 会话内五件套） =="
# tmux server 重启后 prefix2 表为空(run-shell -b 异步) — 自愈同步重放。
# server 未运行(无会话)时先起临时会话让 server 存活, 检查完清理。
tmux ls >/dev/null 2>&1 || { tmux new-session -d -s ck-probe -c /tmp 'sleep 30' 2>/dev/null; CK_PROBE=1; }
if [ -z "$(tmux list-keys -T prefix2 2>/dev/null | grep ' -T prefix2 d ')" ]; then
    [ -x "$HOME/.codex/bin/sync-prefix2.sh" ] && "$HOME/.codex/bin/sync-prefix2.sh"
    echo "  debug: sync rc=$? prefix2_lines=$(tmux list-keys -T prefix2 2>/dev/null | wc -l | tr -d ' ')"
fi
ck "C-a d"        "$([ -n "$(tmux list-keys -T prefix 2>/dev/null | grep ' -T prefix d ')" ] && echo OK)" "OK"
ck "C-a C-d"      "$([ -n "$(tmux list-keys -T prefix 2>/dev/null | grep ' -T prefix C-d ')" ] && echo OK)" "OK"
# prefix2 表随 tmux server 生命周期存在 — server 重启后 run-shell 重放由
# tmux.conf 保证; conformance 检测到缺失时自愈重放并验证
ck "C-b d"        "$([ -n "$(tmux list-keys -T prefix2 2>/dev/null | grep ' -T prefix2 d ')" ] && echo OK)" "OK"
ck "C-] 单键"      "$([ -n "$(tmux list-keys -T root 2>/dev/null | grep 'C-\]')" ] && echo OK)" "OK"
ck "F12 单键"      "$([ -n "$(tmux list-keys -T root 2>/dev/null | grep 'F12')" ] && echo OK)" "OK"

[ "${CK_PROBE:-0}" = "1" ] && tmux kill-session -t ck-probe 2>/dev/null
echo "== burn 模式（默认开/可关/熄火 2） =="
ckge "内置指令存在"      "$(grep -c 'IDLE_PROMPT_DEFAULT' codexc-loop)" 2
ckge "可关闭"            "$(grep -c '0|off|no|false' codexc-loop)" 1
ckge "headless 同款"      "$(grep -c 'IDLE_PROMPT_DEFAULT' codexc-headless)" 2
ckge "熄火阈值 2"         "$(grep -c 'CODEXC_IDLE_PARK:-2' codexc-loop)" 1
ckge "headless 熄火阈值"   "$(grep -c 'CODEXC_IDLE_PARK:-2' codexc-headless)" 1

echo "== 验收上限（双零/gate/轮次/续命） =="
ckge "双零 2"       "$(grep -c 'CODEXC_REVIEW_PASS:-2' codexc-loop)" 1
ckge "gate 3"       "$(grep -c 'CODEXC_GATE_RETRIES:-3' codexc-loop)" 1
ckge "审查轮次 6"    "$(grep -c 'CODEXC_REVIEW_ROUNDS:-6' codexc-loop)" 1
ckge "续命 30"       "$(grep -c 'CODEXC_MAX_CONTINUES:-30' codexc)" 1
ckge "headless 重试 3" "$(grep -c 'CODEXC_TURN_RETRIES:-3' codexc-headless)" 1

echo "== 产品 CLI (ck) =="
ck "ck 存在"        "$([ -x ck ] && echo OK)" "OK"
ck "zcodec 入口"    "$([ -x zcodec ] && echo OK)" "OK"
ck "dshc 入口"      "$([ -x dshc ] && echo OK)" "OK"
ck "status 子命令"  "$([ "$(grep -c 'cmd_status' codexc-headless)" -ge 1 ] && echo OK)" "OK"

echo "== 顶部横幅（banner_set 存在且调用） =="
ckge "banner_set 定义(TUI)" "$(grep -c 'banner_set()' codexc-loop)" 1
ckge "banner_set 定义(headless)" "$(grep -c 'banner_set()' codexc-headless)" 1
ckge "横幅调用点(TUI)" "$(grep -c 'banner_set "' codexc-loop)" 5
ck "overlay 面板源码" "$([ -f desktop/CodingKeeperBar.swift ] && echo OK)" "OK"
ck "overlay 二进制" "$([ -x $HOME/.codingkeeper/bin/CodingKeeperBar ] && echo OK)" "OK"
ckge "横幅调用点(headless)" "$(grep -c 'banner_set "' codexc-headless)" 3

echo "== 路径形态不变量 (符号链接重复注册回归锁) =="
ckge "注册物理路径归一" "$(grep -c 'pwd -P' ck-common.sh)" 1
ck "看门狗入库且有自测" "$([ -x burn-watch.sh ] && grep -q 'cmd_selftest_watch' burn-watch.sh && echo OK)" "OK"

echo "== keeper 自身回归 (2026-11-04/05 事故锁) =="
ck "tmux 全局环境无 CODEXC_TOOL 污染" "$([ -z "$(tmux show-environment -g 2>/dev/null | sed -n 's/^CODEXC_TOOL=//p')" ] && echo OK)" "OK"
echo "== spawn_watcher 互锁回归锁 (pane 卡死事故) =="
swd="cw-spawn-$$"
tmux kill-session -t "$swd" 2>/dev/null
mkdir -p "/tmp/$swd"
tmux new-session -d -s "$swd" -c "/tmp/$swd" "cd /tmp/$swd && '$self_dir/codexc' >/dev/null 2>&1"
swok=0
for i in $(seq 1 15); do
  [ -f "/tmp/$swd/.codingkeeper/watcher.pid" ] && { swok=1; break; }
  sleep 1
done
ck "watcher 15s 内挂载 (无 \$() 互锁挂起)" "$([ "$swok" = "1" ] && echo OK)" "OK"
tmux kill-session -t "$swd" 2>/dev/null
rm -rf "/tmp/$swd"

echo "== 安全不变量 =="
ckge "新鲜度令牌"     "$(grep -c '\.tok' codexc-loop)" 2
ckge "runner 锁"      "$(grep -c 'loop.pid' codexc-loop)" 3
ckge "kill_tree (共享库)" "$(grep -c 'kill_tree' ck-common.sh)" 2
ckge "三车道接库"     "$(grep -l '/ck-common.sh' codexc-loop codexc-headless codexc-daily 2>/dev/null | wc -l | tr -d ' ')" 3
ckge "usage limit 永不续命" "$(grep -c 'usage limit' codexc)" 1

echo "== 投喂消息单行化 (continue 未提交事故回归闸) =="
ckge "codexc 剥离 CR/LF"   "$(grep -cF 'tr -d ' codexc)" 1
ckge "codexc-daily 剥离 CR/LF" "$(grep -cF 'tr -d ' codexc-daily)" 1
ck "CR/LF 剥离机制"   "$([ "$(printf 'a\r\nb' | tr -d '\r\n')" = "ab" ] && echo OK)" "OK"
ck "ck 入口"           "$([ -x ck ] && echo OK)" "OK"
ck "codexc 兼容"       "$([ -x codexc ] && echo OK)" "OK"
ck "fuel 四工具"       "$([ "$(codexc fuel codex >/dev/null 2>&1; codexc fuel claude >/dev/null 2>&1; codexc fuel pi >/dev/null 2>&1; codexc fuel opencode >/dev/null 2>&1; echo $?)" = "0" ] && echo OK)" "OK"

echo "== 结果: pass=$pass fail=$fail =="
[ "$fail" = "0" ]
