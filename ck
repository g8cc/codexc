#!/bin/bash
# ck — CodingKeeper 统一入口
#
# 子命令:
#   ck codex [args]       codex TUI 会话（默认工具）
#   ck claude [args]      Claude Code TUI 会话
#   ck pi [args]          pi TUI 会话
#   ck opencode [args]    opencode TUI 会话
#   ck zcode [args]       同 zcodec: 裸=唤起 ZCode 应用, run=无人值守 runner
#   ck dsh [args]         同 dshc: run=无人值守 runner, 其余见 dshc 说明
#   ck status             跨项目总览
#   ck fuel [tool]        燃料表
#   ck init [tool]        项目脚手架
#   ck leaves [args]      离线审计叶子队列 (--registry 查看全部登记项目)
#   ck prompts [args]     改进燃料库 (list/show/add/packs/enable/disable)
#   ck enqueue [args]     添加队列任务 (文本/--file/--prompt)
#   ck propose [args]     留下待人类决策的改进工单 (文本/--file)
#   ck morning [args]     跨项目晨报 (--hours 12 / --json)
#   ck --help             本帮助
set -u

SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
REPO="$(dirname "$SELF")"

case "${1:-help}" in
    codex)
        shift; exec env CODEXC_TOOL=codex "$REPO/codexc" "$@" ;;
    claude)
        shift; exec env CODEXC_TOOL=claude "$REPO/codexc" "$@" ;;
    pi)
        shift; exec env CODEXC_TOOL=pi "$REPO/codexc" "$@" ;;
    opencode)
        shift; exec env CODEXC_TOOL=opencode "$REPO/codexc" "$@" ;;
    zcode)
        shift; exec "$REPO/zcodec" "$@" ;;   # 语义单点在 zcodec: 裸=TUI, run=自动
    dsh)
        shift; exec "$REPO/dshc" "$@" ;;     # 语义单点在 dshc: 裸=说明, run=自动
    status)
        shift; exec "$REPO/codexc-headless" status "$@" ;;
    leaves)
        shift; exec python3 "$REPO/ck-leaves.py" "$@" ;;
    prompts)
        shift; exec python3 "$REPO/ck-prompts.py" "${@:-list}" ;;
    enqueue)
        shift; exec python3 "$REPO/ck-prompts.py" enqueue "$@" ;;
    propose)
        shift; exec python3 "$REPO/ck-prompts.py" propose "$@" ;;
    interaction)
        shift; exec python3 "$REPO/ck-interaction.py" "$@" ;;
    morning)
        shift; exec python3 "$REPO/ck-morning.py" "$@" ;;
    fuel)
        shift; exec "$REPO/codexc" fuel "$@" ;;
    init)
        # 委托给 codexc-loop init: 会探测测试命令生成 gate.sh。tool 仅区分
        # AGENTS.md/CLAUDE.md 约定 — zcode/dsh 等 headless 工具不是合法
        # CODEXC_TOOL, 归一到 codex (AGENTS.md)
        case "${2:-codex}" in claude) TOOL=claude ;; *) TOOL=codex ;; esac
        exec env CODEXC_TOOL="$TOOL" "$REPO/codexc-loop" init ;;
    --help|-h|help)
        sed -n '3,20p' "$0" | sed -E 's/^# ?//'
        ;;
    *)
        echo "ck: unknown command '${1:-}'" >&2
        echo "用法: ck codex|claude|pi|opencode|zcode|dsh|status|fuel|init" >&2
        exit 1
        ;;
esac
