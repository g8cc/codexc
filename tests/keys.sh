#!/bin/bash
# keys — 各工具凭证与二进制健康检查（报告性；不计失败）。
# 明早测试前跑一遍就知道哪把钥匙还没插好。
set -u
self_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$self_dir"
PATH="$self_dir:$PATH"
note() { echo "  $1"; }

echo "== codex =="
note "CLI: $(command -v codex >/dev/null && echo ok || echo MISSING) | 转发健康: $(codexc fuel codex >/dev/null 2>&1 && echo ok || echo 检查)"
echo "== claude =="
note "CLI: $(command -v claude >/dev/null && echo ok || echo MISSING) | 中转(設置于 ~/.claude/settings.json env)"
probe=$(cd /tmp 2>/dev/null && CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}" timeout 60 claude -p "Reply OK" 2>&1 | head -1)
case "$probe" in OK*) note "真回合: ok" ;; *) note "真回合: $probe" ;; esac
echo "== pi =="
note "CLI: $(command -v pi >/dev/null && echo ok || echo MISSING) | 注意: 当前 provider key 已失效(401) — 修复 pi 登录后自检: pi -p 'Reply OK'"
echo "== opencode =="
note "CLI: $(command -v opencode >/dev/null && echo ok || echo MISSING) | 会话库: $(ls ~/.local/share/opencode/opencode.db >/dev/null 2>&1 && echo ok || echo MISSING)"
echo "== zcode =="
note "bundle: $([ -f /Applications/ZCode.app/Contents/Resources/glm/zcode.cjs ] && echo ok || echo MISSING) | node: $(node --version 2>/dev/null || echo MISSING)"
echo "== dsh =="
note "CLI: $(command -v dsh >/dev/null && echo ok || echo MISSING) | 密钥由 keydrop 轮换 — 认证失败先刷 keydrop"
# 探测带 60s 上限: dsh 挂起时 keys.sh 不能跟着挂死
dsh_out="$(mktemp "${TMPDIR:-/tmp}/keys-dsh.XXXXXX")"
echo "Reply OK" | dsh --profile headless - > "$dsh_out" 2>&1 & dsh_pid=$!
dsh_n=0
while kill -0 "$dsh_pid" 2>/dev/null && [ "$dsh_n" -lt 60 ]; do sleep 1; dsh_n=$((dsh_n+1)); done
kill "$dsh_pid" 2>/dev/null; wait "$dsh_pid" 2>/dev/null
probe="$(head -1 "$dsh_out" 2>/dev/null)"; rm -f "$dsh_out"
if [ "$dsh_n" -ge 60 ]; then note "真回合: 超时 (60s 无响应 — dsh 挂起?)"
else
    case "$probe" in *AUTH*|*invalid*) note "真回合: 钥匙失效 ($probe)" ;; "") note "真回合: 空响应" ;; *) note "真回合: ok ($probe)" ;; esac
fi
exit 0
