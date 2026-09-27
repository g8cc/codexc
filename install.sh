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
    ln -sf "$src" "$dest"
    echo "  $dest -> $src"
}

echo "==== scripts ===="
link "$HERE/codexc" "$CODEX_BIN_DIR/codexc"
link "$HERE/codexc-daily" "$CODEX_BIN_DIR/codexc-daily"
link "$HERE/sync-prefix2.sh" "$CODEX_BIN_DIR/sync-prefix2.sh"

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
