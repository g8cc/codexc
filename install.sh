#!/bin/bash
# codexc 安装脚本 — 软链到 ~/.codex/bin/codexc 和 ~/.tmux.conf
# 用法: ./install.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CODEX_BIN_DIR="$HOME/.codex/bin"
DEST="$CODEX_BIN_DIR/codexc"

# 1. codexc 主脚本
mkdir -p "$CODEX_BIN_DIR"
if [ -f "$DEST" ] && [ ! -L "$DEST" ]; then
    cp "$DEST" "$DEST.bak.$(date +%Y%m%d_%H%M%S)"
    echo "已备份原文件: $DEST.bak.$(date +%Y%m%d_%H%M%S)"
fi
ln -sf "$HERE/codexc" "$DEST"
echo "codexc -> $DEST"

# 2. tmux.conf（可选）
if [ -f "$HOME/.tmux.conf" ] && [ ! -L "$HOME/.tmux.conf" ]; then
    cp "$HOME/.tmux.conf" "$HOME/.tmux.conf.bak.$(date +%Y%m%d_%H%M%S)"
    echo "已备份原文件: $HOME/.tmux.conf.bak.$(date +%Y%m%d_%H%M%S)"
fi
ln -sf "$HERE/tmux.conf" "$HOME/.tmux.conf"
echo "tmux.conf -> $HOME/.tmux.conf"

echo
echo "安装完成。依赖: tmux, sqlite3, python3, codex CLI（均在 PATH 中）"
echo "如果 zshrc 里已有 alias codexc=..., 指向的路径不变, 无需修改。"
