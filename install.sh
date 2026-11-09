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
link "$HERE/ck-zcode-session.py" "$CODEX_BIN_DIR/ck-zcode-session.py"
link "$HERE/ck-dsh-session.py" "$CODEX_BIN_DIR/ck-dsh-session.py"
link "$HERE/ck-prompts.py" "$CODEX_BIN_DIR/ck-prompts.py"
link "$HERE/ck-leaves.py" "$CODEX_BIN_DIR/ck-leaves.py"
link "$HERE/ck-review-process.py" "$CODEX_BIN_DIR/ck-review-process.py"
link "$HERE/ck-watch-tools.sh" "$CODEX_BIN_DIR/ck-watch-tools.sh"
link "$HERE/ck-watcher.py" "$CODEX_BIN_DIR/ck-watcher.py"
link "$HERE/ck-night-loop.py" "$CODEX_BIN_DIR/ck-night-loop.py"
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
ver_ge() {  # ver_ge <版本> <最低> — 逐段数值比较 (BSD 无 sort -V; 尾缀字母截断)
    awk -v a="${1%[a-zA-Z]}" -v b="${2%[a-zA-Z]}" 'BEGIN {
        n = split(a, x, "."); m = split(b, y, ".")
        for (i = 1; i <= (n > m ? n : m); i++) {
            xa = x[i] + 0; xb = y[i] + 0
            if (xa > xb) exit 0
            if (xa < xb) exit 1
        }
        exit 0
    }'
}
missing=""
for cmd in tmux sqlite3 python3 codex; do
    if command -v "$cmd" >/dev/null 2>&1; then
        echo "  ok: $cmd"
    else
        echo "  MISSING: $cmd"
        missing="$missing $cmd"
    fi
done
# 声明的最低版本 (README): python3 3.11+ / tmux 3.5+; zcodec 通道另需 node >= 24。
# 只查存在性会让太旧的依赖在运行深处才炸 (tomllib ImportError / CSI-u 失灵) —
# 这里按能力/版本拦在安装时, 存在但过旧同样计入 missing。
if command -v python3 >/dev/null 2>&1 && ! python3 -c 'import tomllib' >/dev/null 2>&1; then
    echo "  TOO OLD: python3 ($(python3 --version 2>&1 | sed 's/^Python //')) — 需要 3.11+ (tomllib)"
    missing="$missing python3>=3.11"
fi
if command -v tmux >/dev/null 2>&1 && ! ver_ge "$(tmux -V 2>/dev/null | sed -n 's/^tmux \([0-9][0-9.]*\).*/\1/p')" 3.5; then
    echo "  TOO OLD: tmux ($(tmux -V 2>/dev/null)) — 需要 3.5+ (extended-keys CSI-u)"
    missing="$missing tmux>=3.5"
fi
if command -v node >/dev/null 2>&1; then
    if ! ver_ge "$(node --version 2>/dev/null | sed 's/^v//')" 24; then
        echo "  TOO OLD: node ($(node --version 2>/dev/null)) — zcodec/ck zcode 通道需要 >= 24"
        missing="$missing node>=24"
    fi
else
    echo "  note: node 未装 — zcodec/ck zcode 通道不可用 (codex 通道不受影响)"
fi
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
