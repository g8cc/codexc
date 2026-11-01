#!/bin/bash
# ck — CodingKeeper 统一入口
#
# 子命令:
#   ck codex [args]       codex TUI 会话（默认工具）
#   ck claude [args]      Claude Code TUI 会话
#   ck pi [args]          pi TUI 会话
#   ck opencode [args]    opencode TUI 会话
#   ck zcode run          ZCode headless 夜间通道
#   ck dsh run            dsh headless 夜间通道
#   ck status             跨项目总览
#   ck fuel [tool]        燃料表
#   ck init [tool]        项目脚手架
#   ck --help             本帮助
set -u

SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
REPO="$(dirname "$SELF")"

case "${1:-help}" in
    codex)
        shift; exec "$REPO/codexc" "$@" ;;
    claude)
        shift; exec env CODEXC_TOOL=claude "$REPO/codexc" "$@" ;;
    pi)
        shift; exec env CODEXC_TOOL=pi "$REPO/codexc" "$@" ;;
    opencode)
        shift; exec env CODEXC_TOOL=opencode "$REPO/codexc" "$@" ;;
    zcode)
        shift; export CODEXC_HEADLESS_CMD="${CODEXC_HEADLESS_CMD:-$REPO/codexc-zcode-worker}"
        exec "$REPO/codexc-headless" "$@" ;;
    dsh)
        shift; export CODEXC_HEADLESS_CMD="${CODEXC_HEADLESS_CMD:-$REPO/codexc-dsh-worker}"
        export DSH_DIR="${DSH_DIR:-$HOME/.dsh}"
        exec "$REPO/codexc-headless" "$@" ;;
    status)
        shift; exec "$REPO/codexc-headless" status "$@" ;;
    fuel)
        shift; exec "$REPO/codexc" fuel "$@" ;;
    init)
        TOOL="${2:-codex}"
        # 委托给 codexc-loop init: 会探测测试命令生成 gate.sh, 且按 tool 选
        # AGENTS.md/CLAUDE.md 约定 (codexc-headless init 只是占位脚手架)
        exec env CODEXC_TOOL="$TOOL" "$REPO/codexc-loop" init ;;
    --help|-h|help)
        sed -n '3,16p' "$0" | sed 's/^# \?//'
        ;;
    *)
        echo "ck: unknown command '${1:-}'" >&2
        echo "用法: ck codex|claude|pi|opencode|zcode|dsh|status|fuel|init" >&2
        exit 1
        ;;
esac
