#!/bin/bash
# codexc installer — symlinks the scripts into ~/.codex/bin
#
# Usage:
#   ./install.sh                install codexc + codexc-daily (no tmux changes)
#   ./install.sh --with-tmux    ALSO replace ~/.tmux.conf with this repo's
#                               config (existing file is backed up first).
#                               Skip if you already have your own tmux setup —
#                               the lines to merge manually are shown below.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CODEX_BIN_DIR="$HOME/.codex/bin"

link() {  # link <src> <dest>
    local src="$1" dest="$2" stamp backup suffix
    mkdir -p "$(dirname "$dest")"
    if [ -f "$dest" ] && [ ! -L "$dest" ]; then
        stamp="$(date +%Y%m%d_%H%M%S)"
        backup="$dest.bak.$stamp"
        suffix=1
        while [ -e "$backup" ]; do
            backup="$dest.bak.$stamp.$suffix"
            suffix=$((suffix + 1))
        done
        cp -p "$dest" "$backup"
        echo "  backed up existing: $backup"
    fi
    if [ -d "$dest" ] && [ ! -L "$dest" ]; then
        echo "install: refusing to replace directory: $dest" >&2
        return 1
    fi
    # -n replaces a symlink to a directory instead of linking inside its target.
    ln -sfn "$src" "$dest"
    echo "  $dest -> $src"
}

echo "==== scripts ===="
link "$HERE/ck" "$CODEX_BIN_DIR/ck"
link "$HERE/ck-common.sh" "$CODEX_BIN_DIR/ck-common.sh"   # 三车道共享底层 (被 source)
link "$HERE/ck-config.py" "$CODEX_BIN_DIR/ck-config.py"
link "$HERE/ck-window.py" "$CODEX_BIN_DIR/ck-window.py"
link "$HERE/ck-leaf.py" "$CODEX_BIN_DIR/ck-leaf.py"
link "$HERE/ck-prompts.py" "$CODEX_BIN_DIR/ck-prompts.py"
link "$HERE/ck-leaves.py" "$CODEX_BIN_DIR/ck-leaves.py"
link "$HERE/ck-review-process.py" "$CODEX_BIN_DIR/ck-review-process.py"
link "$HERE/ck-watch-tools.sh" "$CODEX_BIN_DIR/ck-watch-tools.sh"
link "$HERE/ck-watcher.py" "$CODEX_BIN_DIR/ck-watcher.py"
link "$HERE/codexc" "$CODEX_BIN_DIR/codexc"   # backward compat
# 内部实现脚本（ck 通过绝对路径调用）
link "$HERE/codexc-loop" "$CODEX_BIN_DIR/codexc-loop"
link "$HERE/codexc-headless" "$CODEX_BIN_DIR/codexc-headless"
link "$HERE/codexc-zcode-worker" "$CODEX_BIN_DIR/codexc-zcode-worker"
link "$HERE/codexc-review-leaf" "$CODEX_BIN_DIR/codexc-review-leaf"
link "$HERE/codexc-dsh-worker" "$CODEX_BIN_DIR/codexc-dsh-worker"
link "$HERE/zcodec" "$CODEX_BIN_DIR/zcodec"   # 产品命名入口 (无参为交互入口)
link "$HERE/dshc" "$CODEX_BIN_DIR/dshc"
link "$HERE/codexc-daily" "$CODEX_BIN_DIR/codexc-daily"
link "$HERE/sync-prefix2.sh" "$CODEX_BIN_DIR/sync-prefix2.sh"

echo
echo "==== desktop menubar (可选, 需 swiftc) ===="
if command -v swiftc >/dev/null 2>&1 && [ -f "$HERE/desktop/CodingKeeperBar.swift" ]; then
    mkdir -p "$HOME/.codingkeeper/bin"
    swiftc -O -o "$HOME/.codingkeeper/bin/CodingKeeperBar" "$HERE/desktop/CodingKeeperBar.swift" 2>/dev/null \
        && echo "  built: $HOME/.codingkeeper/bin/CodingKeeperBar (启动: 直接运行该文件)" \
        || echo "  build failed — 面板暂不可用"
else
    echo "  skipped (无 swiftc 或源码缺失)"
fi

echo
echo "==== dependencies ===="
missing=""
for cmd in tmux sqlite3 python3 codex; do
    if command -v "$cmd" >/dev/null 2>&1; then
        echo "  ok: $cmd"
    else
        echo "  MISSING: $cmd"
        missing="$missing $cmd"
    fi
done
if [ -n "$missing" ]; then
    echo
    echo "  Install the above before using codexc, e.g.:"
    echo "    brew install tmux sqlite python3 && npm i -g @openai/codex"
fi

echo
echo "==== tmux config (optional) ===="
if [ "${1:-}" = "--with-tmux" ]; then
    link "$HERE/tmux.conf" "$HOME/.tmux.conf"
    echo "  note: run 'tmux source-file ~/.tmux.conf' (or restart tmux) to apply."
else
    cat <<'EOF'
  skipped — your ~/.tmux.conf was left untouched. codexc works without it,
  but these lines fix Shift+Enter / mouse scroll / prefix keys:

    set -s extended-keys on
    set -s extended-keys-format csi-u          # tmux >= 3.5
    set -as terminal-features 'xterm*:extkeys'
    set -g mouse on
    set -g history-limit 5000
    set -g prefix C-a
    set -g prefix2 C-b
    bind C-a send-prefix
    run-shell -b "$HOME/.codex/bin/sync-prefix2.sh"

  Merge them into your config, or re-run: ./install.sh --with-tmux
EOF
fi

echo
echo "Done. Next steps:"
echo "  codexc                      open this directory's codex session"
echo "  codexc resume --last        continue the most recent codex session"
echo "  codexc -t 10:00 \"prompt\"    queue a prompt at a specific time"
echo "  codexc-daily install 10:00  daily auto-resume at 10:00 (optional)"
echo "  codexc -h                   all options"
