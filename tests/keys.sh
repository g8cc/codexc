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
note "真回合: 请显式运行各 CLI 自检；统一回归不发送模型请求"
echo "== pi =="
note "CLI: $(command -v pi >/dev/null && echo ok || echo MISSING) | 登录自检: pi -p 'Reply OK'"
echo "== opencode =="
note "CLI: $(command -v opencode >/dev/null && echo ok || echo MISSING) | 会话库: $(ls ~/.local/share/opencode/opencode.db >/dev/null 2>&1 && echo ok || echo MISSING)"
echo "== zcode =="
note "bundle: $([ -f /Applications/ZCode.app/Contents/Resources/glm/zcode.cjs ] && echo ok || echo MISSING) | node: $(node --version 2>/dev/null || echo MISSING)"
echo "== dsh =="
note "CLI: $(command -v dsh >/dev/null && echo ok || echo MISSING) | 密钥由 keydrop 轮换 — 认证失败先刷 keydrop"
note "真回合: 已跳过（离线报告）"
exit 0
